"""Eeshu's AI persona — LiveKit voice agent.

Latency budget for <2s first response (measured at the caller's ear):
  Deepgram Nova-3 streaming STT        ~150-300ms after end of speech
  Turn detection (VAD + EOU model)     ~200ms
  gemini-2.5-flash first token (stream) ~350-500ms
  ElevenLabs Flash v2.5 first audio    ~100-200ms
  + preemptive_generation=True: LLM+TTS start on interim transcripts,
    before end-of-turn is committed, hiding most of the LLM latency.

Knowledge questions add one RAG tool call (~300ms: query embedding + in-process
cosine search — no HTTP hop, the corpus file is loaded into memory at startup).
The agent speaks a short filler line before slow tools so the line never goes
silent.

Run locally:   python agent.py console        (terminal mic test, no telephony)
               python agent.py dev            (connect to LiveKit Cloud)
Deploy:        python agent.py start          (production worker)
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from shared.provider import configure_provider  # noqa: E402

from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    function_tool,
)
from livekit.agents import llm as agents_llm
from livekit.agents import tts as agents_tts
from livekit.plugins import deepgram, elevenlabs, openai, silero
from livekit.plugins.turn_detector.english import EnglishModel

from shared import calcom
from shared.persona import VOICE_SYSTEM_PROMPT, current_time_context
from shared.rag import get_store

logger = logging.getLogger("persona-agent")

AGENT_NAME = "eeshu-persona"


class PersonaAgent(Agent):
    def __init__(self) -> None:
        # One agent instance per call, so the timestamp is fresh per session.
        super().__init__(instructions=VOICE_SYSTEM_PROMPT + current_time_context())

    @function_tool()
    async def search_background(self, context: RunContext, query: str) -> str:
        """Search Eeshu's resume, GitHub repos, READMEs and merged PRs. Call this
        before stating any specific fact about his background, projects, or skills.

        Args:
            query: What to look up, e.g. "FinMatch architecture" or "KMesh Rust work".
        """
        store = get_store()
        results = await asyncio.to_thread(store.search, query, 4)
        return store.format_results(results)

    @function_tool()
    async def get_availability(self, context: RunContext, timezone: str = "") -> str:
        """Get Eeshu's real open interview slots for the next 7 days.

        Args:
            timezone: IANA timezone of the caller, e.g. "Asia/Kolkata". Optional.
        """
        # Guaranteed filler while the calendar API runs (~1-2s) — speaking it
        # here beats prompting the LLM to say it: it always plays and adds no
        # generation latency on top of the tool latency.
        context.session.say("One sec, let me check his calendar.")
        tz = timezone or calcom.DEFAULT_TZ
        slots = await asyncio.to_thread(calcom.get_available_slots, 7, tz)
        if not slots:
            return "No open slots in the next 7 days."
        return (
            calcom.format_slots_human(slots, tz, limit=6)
            + "\nRaw ISO starts (use exactly when booking): "
            + ", ".join(slots[:10])
        )

    @function_tool()
    async def book_meeting(
        self,
        context: RunContext,
        start_iso: str,
        name: str,
        email: str,
        timezone: str = "",
    ) -> str:
        """Book a confirmed interview on Eeshu's real calendar. Only call after the
        caller picked a slot and confirmed their name and email (read the email
        back letter by letter first).

        Args:
            start_iso: Slot start in ISO 8601, exactly as returned by get_availability.
            name: Caller's full name.
            email: Caller's email address.
            timezone: Caller's IANA timezone. Optional.
        """
        context.session.say("Okay, locking that in now.")
        result = await asyncio.to_thread(
            calcom.create_booking,
            start_iso,
            name,
            email,
            timezone or calcom.DEFAULT_TZ,
            "Booked via Eeshu's AI voice agent",
        )
        if result.get("success"):
            return (
                f"BOOKED. Start: {result['start']}. "
                f"Confirmation email sent to the attendee."
            )
        return f"BOOKING FAILED: {result.get('error')}. Offer another slot."


async def entrypoint(ctx: JobContext) -> None:
    # Routes the openai client at Gemini and sets model env vars. Done here (not
    # at import) so `agent.py download-files` in the Docker build doesn't require
    # secrets that only exist at runtime.
    configure_provider()
    await ctx.connect()

    tts = agents_tts.FallbackAdapter(
        [
            # Primary: ElevenLabs Flash v2.5 — ~75ms model latency.
            # api_key passed explicitly: the plugin's env fallback looks for
            # ELEVEN_API_KEY, not our ELEVENLABS_API_KEY.
            elevenlabs.TTS(
                model="eleven_flash_v2_5",
                voice_id=os.environ["ELEVENLABS_VOICE_ID"],
                api_key=os.environ["ELEVENLABS_API_KEY"],
                # Lower stability = more pitch variation = less robotic.
                voice_settings=elevenlabs.VoiceSettings(
                    stability=0.45, similarity_boost=0.8
                ),
            ),
            # Fallback: Deepgram Aura-2 (same API key as STT) — survives
            # ElevenLabs quota exhaustion during the 7-day live window.
            deepgram.TTS(model="aura-2-orion-en"),
        ]
    )

    # Free-tier daily quotas are per-model AND per-key — fall back across the
    # full matrix (key rotation first, then model downgrade) so a mid-call
    # quota hit degrades quality instead of dropping audio.
    from shared.provider import GEMINI_BASE_URL, gemini_api_keys

    voice_models = [os.environ["VOICE_MODEL"]] + [
        m.strip() for m in os.environ.get("FALLBACK_MODELS", "").split(",") if m.strip()
    ]
    llm = agents_llm.FallbackAdapter(
        [
            openai.LLM(model=m, api_key=k, base_url=GEMINI_BASE_URL, temperature=0.4)
            for m in voice_models
            for k in gemini_api_keys()
        ]
    )

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=llm,
        tts=tts,
        vad=silero.VAD.load(),
        turn_detection=EnglishModel(),
        # Start LLM+TTS on interim transcripts; discard if the user keeps talking.
        preemptive_generation=True,
        allow_interruptions=True,
    )

    await session.start(agent=PersonaAgent(), room=ctx.room)

    # Fixed greeting via say(): no LLM round-trip, so first audio reaches the
    # caller in well under a second. (Also: Gemini's OpenAI-compat endpoint
    # rejects generate_reply's system-only request — "contents is not
    # specified".)
    session.say(
        "Hey! This is Eeshu's AI — he set me up to talk through his work "
        "and book interviews. What can I do for you?"
    )


if __name__ == "__main__":
    agents.cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME)
    )
