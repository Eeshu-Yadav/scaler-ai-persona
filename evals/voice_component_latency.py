"""Measure per-component voice latency to validate the <2s first-response budget.

End-to-end first-response latency on a real phone call = STT finalization +
turn detection + LLM first token + TTS first byte + transport. This script
measures the three API components directly (the controllable parts); transport
and turn-detection are measured from LiveKit session logs on real calls
(see voice_test_log.md).

Usage:
  OPENAI_API_KEY=... DEEPGRAM_API_KEY=... ELEVENLABS_API_KEY=... \
    python evals/voice_component_latency.py --runs 10
"""

import argparse
import json
import os
import statistics
import time

import requests
from openai import OpenAI

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / "voice-agent" / ".env")

from shared.provider import configure_provider  # noqa: E402

configure_provider()

from shared.persona import VOICE_SYSTEM_PROMPT  # noqa: E402

SAMPLE_QUESTION = "Tell me briefly about Eeshu's experience with RAG pipelines."
SAMPLE_TTS_TEXT = "Sure — Eeshu has built RAG pipelines in production, including this very assistant."


def llm_first_token(client: OpenAI, model: str) -> float:
    t0 = time.perf_counter()
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VOICE_SYSTEM_PROMPT},
            {"role": "user", "content": SAMPLE_QUESTION},
        ],
        stream=True,
        max_tokens=80,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            return time.perf_counter() - t0
    return time.perf_counter() - t0


def elevenlabs_ttfb(voice_id: str) -> float:
    t0 = time.perf_counter()
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": SAMPLE_TTS_TEXT, "model_id": "eleven_flash_v2_5"},
        params={"optimize_streaming_latency": 3},
        stream=True,
        timeout=30,
    )
    resp.raise_for_status()
    for _ in resp.iter_content(chunk_size=1024):
        return time.perf_counter() - t0
    return time.perf_counter() - t0


def deepgram_stt_prerecorded() -> float:
    """Proxy metric: REST round-trip on a short utterance. Streaming finalization
    on live calls is faster; this gives an upper bound."""
    # 0.5s of silence WAV (valid minimal payload for a timing probe)
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<" + "h" * 8000, *([0] * 8000)))
    t0 = time.perf_counter()
    resp = requests.post(
        "https://api.deepgram.com/v1/listen?model=nova-3",
        headers={
            "Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}",
            "Content-Type": "audio/wav",
        },
        data=buf.getvalue(),
        timeout=30,
    )
    resp.raise_for_status()
    return time.perf_counter() - t0


def pstats(name: str, xs: list[float]) -> dict:
    xs_ms = [round(x * 1000) for x in xs]
    out = {
        "component": name,
        "p50_ms": round(statistics.median(xs_ms)),
        "p95_ms": round(sorted(xs_ms)[max(0, int(len(xs_ms) * 0.95) - 1)]),
        "mean_ms": round(statistics.mean(xs_ms)),
        "runs": len(xs_ms),
    }
    print(f"{name:28} p50={out['p50_ms']}ms  p95={out['p95_ms']}ms  mean={out['mean_ms']}ms")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    client = OpenAI()
    model = os.environ["VOICE_MODEL"]
    voice = os.environ["ELEVENLABS_VOICE_ID"]

    llm, tts, stt = [], [], []
    for i in range(args.runs):
        print(f"run {i + 1}/{args.runs}", end="\r")
        llm.append(llm_first_token(client, model))
        tts.append(elevenlabs_ttfb(voice))
        stt.append(deepgram_stt_prerecorded())
        time.sleep(0.5)

    print()
    results = [
        pstats(f"LLM first token ({model})", llm),
        pstats("ElevenLabs Flash TTFB", tts),
        pstats("Deepgram round-trip (proxy)", stt),
    ]
    budget = sum(r["p50_ms"] for r in results[:2])  # STT streams during speech
    print(f"\nLLM + TTS p50 chain: {budget}ms "
          f"(+ ~300-500ms turn detection & transport → first-response estimate)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "voice_component_latency.json")
    json.dump(results, open(path, "w"), indent=2)
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
