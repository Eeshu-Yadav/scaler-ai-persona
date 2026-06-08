"""RAG + tool-calling chat engine. Yields SSE events for streaming responses.

Event protocol (each yielded string is one SSE `data:` line, JSON-encoded):
  {"type": "delta", "text": "..."}        — assistant text token(s)
  {"type": "tool", "name": "...", "args": {...}}  — a tool is being executed
  {"type": "sources", "items": [...]}     — retrieval citations for the answer
  {"type": "done"}                        — end of turn
  {"type": "error", "message": "..."}
"""

import json
import logging
import re
import time

from django.conf import settings
from openai import APIError

from shared import calcom
from shared.persona import CHAT_SYSTEM_PROMPT, current_time_context
from shared.rag import get_store

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_background",
            "description": (
                "Search Eeshu's resume, GitHub repos, READMEs, commits, and merged "
                "PRs. ALWAYS call this before stating any specific fact about his "
                "background, projects, or skills."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_availability",
            "description": "Get Eeshu's real open interview slots from his calendar (next 7 days).",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone, default Asia/Kolkata"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_meeting",
            "description": (
                "Book a confirmed interview slot on Eeshu's real calendar. Only call "
                "after the user has picked a slot and given their name and email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_iso": {"type": "string", "description": "Slot start time in ISO 8601 exactly as returned by get_availability"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "timezone": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["start_iso", "name", "email"],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 30


def _run_tool(name: str, args: dict) -> tuple[str, list | None]:
    """Execute a tool. Returns (result_for_llm, sources_or_none)."""
    if name == "search_background":
        query = (args.get("query") or "").strip()
        if not query:
            return "TOOL_ERROR: empty query — call again with a specific query string.", None
        store = get_store()
        results = store.search(query, top_k=5)
        sources = [
            {"source": r["source"], "title": r["title"], "score": r["score"]}
            for r in results
        ]
        return store.format_results(results), sources
    if name == "get_availability":
        tz = args.get("timezone") or calcom.DEFAULT_TZ
        slots = calcom.get_available_slots(days_ahead=7, timezone_name=tz)
        if not slots:
            return "No open slots in the next 7 days.", None
        # Give the LLM both human-readable summary and the raw ISO starts it
        # must echo into book_meeting.
        return (
            calcom.format_slots_human(slots, tz)
            + "\nRaw ISO starts (use exactly for booking): "
            + ", ".join(slots[:12]),
            None,
        )
    if name == "book_meeting":
        result = calcom.create_booking(
            start_iso=args["start_iso"],
            attendee_name=args["name"],
            attendee_email=args["email"],
            timezone_name=args.get("timezone") or calcom.DEFAULT_TZ,
            notes=args.get("notes", ""),
        )
        return json.dumps(result), None
    return f"Unknown tool: {name}", None


def stream_chat(history: list[dict]):
    """history: [{role: user|assistant, content: str}, ...] — yields SSE event dicts."""
    messages = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT + current_time_context()}
    ]
    for m in history[-MAX_HISTORY_MESSAGES:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            messages.append({"role": m["role"], "content": m["content"][:8000]})

    import os

    from shared.provider import gemini_clients_cycled, mark_working_key

    model_chain = [settings.CHAT_MODEL] + [
        m.strip() for m in os.environ.get("FALLBACK_MODELS", "").split(",") if m.strip()
    ]

    def _call(model, cl):
        kwargs = dict(
            model=model, messages=messages, tools=TOOLS,
            stream=True, temperature=0.4, max_tokens=1200,
        )
        # Gemini 2.5 models "think" by default, adding ~1s/call. These answers
        # just synthesize retrieved text, so minimal reasoning is plenty and
        # noticeably faster. (2.0-flash has no thinking and rejects the param.)
        if model.startswith("gemini-2.5"):
            kwargs["reasoning_effort"] = "low"
        return cl.chat.completions.create(**kwargs)

    def create_stream():
        """Free-tier quotas are per-model AND per-key. For each model, cycle
        through the keys starting from the last working one (round-robin, wraps
        to the front); park the cursor on whichever key answers so the next
        request skips the exhausted ones. If the whole matrix is 429, wait once
        (per-minute quota) and retry from the live cursor."""
        last_exc = None
        for model in model_chain:
            for idx, cl in gemini_clients_cycled():
                try:
                    stream = _call(model, cl)
                    mark_working_key(idx)
                    return stream
                except APIError as exc:  # 429, 403, 5xx — skip this key/model
                    last_exc = exc
        m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(last_exc))
        time.sleep(min(float(m.group(1)) if m else 30, 60))
        for idx, cl in gemini_clients_cycled():
            try:
                stream = _call(model_chain[0], cl)
                mark_working_key(idx)
                return stream
            except APIError as exc:
                last_exc = exc
        raise last_exc

    all_sources: list[dict] = []
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            stream = create_stream()
            text_parts: list[str] = []
            tool_calls: dict = {}
            last_key = None
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_parts.append(delta.content)
                    yield {"type": "delta", "text": delta.content}
                for tc in delta.tool_calls or []:
                    # OpenAI streams arguments in fragments keyed by index;
                    # Gemini's compat layer sends each call whole with
                    # index=None — key by id there so parallel calls don't
                    # collapse into one slot.
                    if tc.index is not None:
                        key = ("idx", tc.index)
                    elif tc.id:
                        key = ("id", tc.id)
                    else:
                        key = last_key
                    if key is None:
                        continue
                    last_key = key
                    slot = tool_calls.setdefault(
                        key, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

            if not tool_calls:
                break  # final answer streamed

            # Record the assistant turn, run each tool, loop again.
            # Gemini's OpenAI-compat endpoint rejects content:null and may omit
            # tool-call ids — normalize both.
            for idx, t in enumerate(tool_calls.values()):
                t["id"] = t["id"] or f"call_{idx}"
            messages.append({
                "role": "assistant",
                "content": "".join(text_parts),
                "tool_calls": [
                    {
                        "id": t["id"],
                        "type": "function",
                        "function": {"name": t["name"], "arguments": t["arguments"]},
                    }
                    for t in tool_calls.values()
                ],
            })
            for t in tool_calls.values():
                try:
                    args = json.loads(t["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                safe_args = {k: v for k, v in args.items() if k != "email"} | (
                    {"email": "<redacted>"} if "email" in args else {}
                )
                yield {"type": "tool", "name": t["name"], "args": safe_args}
                try:
                    result, sources = _run_tool(t["name"], args)
                except Exception as exc:  # tool failure must not kill the stream
                    logger.exception("tool %s failed", t["name"])
                    result, sources = f"TOOL_ERROR: {exc}", None
                if sources:
                    all_sources.extend(sources)
                messages.append({
                    "role": "tool",
                    "tool_call_id": t["id"],
                    "content": result[:12000],
                })

        if all_sources:
            yield {"type": "sources", "items": all_sources[:10]}
        yield {"type": "done"}
    except Exception as exc:
        logger.exception("chat stream failed")
        yield {"type": "error", "message": str(exc)[:200]}
        yield {"type": "done"}
