# Evals Report — AI Persona (Eeshu Yadav)

*Voice: <PHONE NUMBER> · Chat: <CHAT URL> · Repo: <REPO URL> · Date: <DATE>*

## 1. Voice quality

**First-response latency** — measured two ways: (a) component benchmarks
(`evals/voice_component_latency.py`, N=10 runs): LLM first token p50 = `<X>`ms,
ElevenLabs Flash TTFB p50 = `<X>`ms; (b) end-to-end stopwatch on `<N>` real calls
(end of caller utterance → first agent audio): **p50 = `<X>`s, p95 = `<X>`s**
(target < 2s). Preemptive generation (LLM/TTS start on interim transcripts)
hides most LLM latency behind turn detection.

**Transcription accuracy** — sampled `<N>` utterances across `<N>` calls against
LiveKit session transcripts: **`<X>`% word accuracy** (Deepgram Nova-3).

**Task completion (booking)** — `<N>` scripted booking calls (happy path, timezone
change, slot change mid-flow, spelled emails): **`<X>/<N>` confirmed** —
verified by Cal.com confirmation email + Google Calendar event.

## 2. Chat groundedness

Golden set of 20 Q&A cases (10 factual, 3 should-say-unknown, 4 adversarial/
injection, 1 honesty probe, 1 booking, 1 contribution-vs-ownership) — run
end-to-end against the live backend with **Gemini 2.5 Pro as judge**
(`evals/run_chat_evals.py`); judge verdicts spot-checked manually on `<N>` cases.

- **Groundedness rate: `<X>`%** · **Hallucination rate: `<X>`%**
- **Retrieval precision: `<X>`** / **recall: `<X>`** on expected-source labels
  (per-question source prefixes over the corpus of `<N>` chunks).

## 3. Three failure modes found → root cause → fix

1. **Booking failed with "time is in the past" despite listing valid slots.**
   Root cause: the LLM had no notion of the current date — it resolved
   "tomorrow" against its training prior and constructed a stale ISO timestamp
   instead of reusing the tool's output. Fix: inject current IST datetime into
   the system prompt per-request + hard rule to copy `start_iso` verbatim from
   `get_availability`. Re-test: booking confirmed end-to-end on Cal.com.
2. **Multi-search answers silently broke on Gemini (HTTP 400 mid-stream).**
   Root cause: Gemini's OpenAI-compatible endpoint streams parallel tool calls
   with `index=None`, so an index-keyed accumulator collapsed all calls into
   one slot, concatenating their JSON args into an unparseable string. Fix:
   key the accumulator by call `id` when `index` is absent; guard empty-query
   embeddings. Re-test: 3 parallel targeted searches per broad question.
3. **Mid-conversation hard failures once free-tier quota ran out (20 req/day
   /model/key).** Root cause: single-model, single-key dependency. Fix:
   fallback matrix — rotate API keys first (keeps the best model), then
   degrade through sibling models (`flash → flash-lite → 2.0-flash`) in both
   chat and voice (LiveKit `FallbackAdapter`). Re-test: booking flow succeeded
   while the primary model's daily bucket was exhausted.

## 4. Conscious tradeoff

**In-memory vector store over a managed vector DB.** The corpus is ~`<N>` chunks
(one resume + ~20 repos). Precomputed embeddings in a JSON file, loaded into a
numpy matrix at boot: retrieval is <5ms with zero infra and zero per-query cost;
the voice agent does RAG in-process, removing an HTTP hop from the latency
budget. Cost: redeploy to update the corpus and no scaling story — acceptable
for a single-persona corpus that changes at most weekly.

## 5. With 2 more weeks

- Voice: cloned voice (ElevenLabs) of my actual voice; speculative tool
  prefetch (start RAG retrieval from interim transcripts); WebRTC chat-to-voice
  handoff on the same persona.
- RAG: hybrid BM25+dense retrieval with reranking; nightly GitHub re-ingestion;
  per-claim citation rendering in chat.
- Evals: CI-gated eval runs on every prompt change; automated voice eval rig
  (TTS-generated caller + scripted dialogues over SIP) replacing manual call logs.
