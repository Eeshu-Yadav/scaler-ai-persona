"""Gemini provider configuration — the sole LLM/embeddings provider.

Gemini exposes an OpenAI-compatible endpoint, so the stack talks to it through
the `openai` client library (that package is just the HTTP transport — there is
no OpenAI account or key anywhere in this project; Google documents this exact
usage). Call configure_provider() once at every entry point after load_dotenv().
"""

import os
import threading

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Round-robin cursor over the API keys. Persisted at module level so it
# survives across requests in a long-running worker: once a key is found
# working, the next request starts there instead of re-hitting exhausted
# keys from the top; when that key exhausts we advance and wrap to the front
# (where a key's daily quota may have since reset).
_key_cursor = 0
_key_lock = threading.Lock()

MODEL_DEFAULTS = {
    "CHAT_MODEL": "gemini-2.5-flash",
    "VOICE_MODEL": "gemini-2.5-flash",
    # gemini-2.5-pro has zero free-tier quota; flash is the judge on free tier.
    "JUDGE_MODEL": "gemini-2.5-flash",
    "EMBEDDING_MODEL": "gemini-embedding-001",
    # Free-tier daily quotas are per-model — when the primary's bucket is
    # exhausted, fall through these (comma-separated) instead of going down.
    "FALLBACK_MODELS": "gemini-2.5-flash-lite,gemini-2.0-flash",
}


def gemini_api_keys() -> list[str]:
    """Primary key plus numbered fallbacks (GEMINI_API_KEY_1, _2, ...).
    Each key has its own free-tier daily quota, so rotating keys before
    downgrading models keeps the best model in play longest."""
    keys = [os.environ.get("GEMINI_API_KEY", "").strip()]
    i = 1
    while os.environ.get(f"GEMINI_API_KEY_{i}", "").strip():
        keys.append(os.environ[f"GEMINI_API_KEY_{i}"].strip())
        i += 1
    return [k for k in keys if k]


def gemini_clients_cycled():
    """Yield (index, OpenAI client) for every key, ordered starting from the
    rotating cursor and wrapping around — so exhausted keys aren't retried
    first. Call mark_working_key(index) after a successful request to park the
    cursor on the live key."""
    from openai import OpenAI

    keys = gemini_api_keys()
    with _key_lock:
        start = _key_cursor % len(keys)
    order = [(start + i) % len(keys) for i in range(len(keys))]
    return [
        (idx, OpenAI(api_key=keys[idx], base_url=GEMINI_BASE_URL)) for idx in order
    ]


def mark_working_key(index: int) -> None:
    global _key_cursor
    with _key_lock:
        _key_cursor = index


def configure_provider() -> str:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set — get a free key at aistudio.google.com/apikey"
        )
    # The openai client library reads these env vars; point it at Gemini.
    os.environ["OPENAI_API_KEY"] = gemini_key
    os.environ["OPENAI_BASE_URL"] = GEMINI_BASE_URL
    for var, default in MODEL_DEFAULTS.items():
        current = os.environ.get(var, "")
        # Override empty values and any stale non-Gemini model names.
        if not current or not current.startswith("gemini"):
            os.environ[var] = default
    return "gemini"
