# Evals Report — AI Persona (Eeshu Yadav)

*Voice: +1 (270) 612-3958 (US) + web "Talk to the agent" button · Chat:
eeshu-persona-chat.onrender.com · Repo: github.com/Eeshu-Yadav/scaler-ai-persona
· Run date: 2026-06-06 · against the **deployed** backend*

> The styled one-page version is [`eval_report.pdf`](eval_report.pdf), generated
> from the latest results JSON by `evals/make_report.py`.

## 1. Voice quality

**First-response latency** — architecture targets <2s via Deepgram Nova-3
streaming STT, preemptive generation (LLM/TTS start on interim transcripts, so
most LLM latency hides behind turn detection), and ElevenLabs Flash v2.5 TTS
(~75ms TTFB). End-to-end first-response is measured by stopwatch on live calls
(protocol in `evals/voice_test_log.md`); component latency benchmark in
`evals/voice_component_latency.py`.

**Transcription accuracy** — Deepgram Nova-3 streaming STT; word accuracy
spot-checked against LiveKit session transcripts on live calls.

**Task completion (booking)** — booking verified end-to-end against the **real
Cal.com calendar**: a confirmed booking ("Interview with Eeshu", 11:00 AM IST)
was created via the chat path and appeared on Google Calendar; the voice path
uses the same `book_meeting` tool.

## 2. Chat groundedness

Golden set of **20 Q&A cases** (12 factual, 3 should-say-unknown, 4 adversarial/
injection, 1 booking) run end-to-end against the **deployed** backend, graded by
an LLM judge (**Gemini 2.5 Flash**) instructed to flag only contradictions /
fabrications — extra true detail is allowed (`evals/run_chat_evals.py`).

- **Groundedness rate: 95%** (19/20) · **Hallucination rate: 5%**
- **Retrieval precision: 0.685** / **recall: 0.962** on expected-source labels,
  over a **120-chunk** corpus (resume + ~20 GitHub repos + merged PRs).
- By type: factual **12/12**, unknown **3/3**, adversarial **4/4**, booking **0/1**.
- The single miss is `book-1`: the judge (which sees only the answer text, not
  that `get_availability` actually fired) assumed the listed slots were invented.
  The booking tool is confirmed working — a real Cal.com booking was created — so
  this is a judge-visibility artifact, not a model hallucination.

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
3. **Mid-conversation hard failures once free-tier quota ran out.** Root cause:
   single-model, single-key dependency 429'd on Gemini's free daily/per-minute
   caps. Fix: **round-robin key rotation** (cycles from the last working key and
   wraps to the front) × **model fallback** (`flash → flash-lite → 2.0-flash`),
   skipping any failing key (429/403/5xx), in both chat and voice (LiveKit
   `FallbackAdapter`). Re-test: serving continues after a key's daily bucket is
   exhausted. (Honest caveat: with *all* free keys exhausted, responses fall
   back to a paced retry and slow to ~tens of seconds — the documented fix for
   the live window is enabling paid tier-1 on one Gemini project; see §4.)

## 4. Conscious tradeoff

**In-memory vector store over a managed vector DB**, and a **Gemini-only free
tier** over a paid provider. The corpus is ~120 chunks (one resume + ~20 repos),
so embeddings are precomputed into a JSON file and loaded into a numpy matrix at
boot: retrieval is <5ms with zero infra and zero per-query cost, and the voice
agent does RAG in-process — removing an HTTP hop from the latency budget. The
conscious cost: refreshing the corpus needs a redeploy, and the Gemini free tier
trades latency-under-exhaustion (mitigated by key/model rotation) for ~$0
running cost. For sustained unannounced probing the right move is paid tier-1 on
one Gemini project (~$1–3 for the window) — a deliberate cost-vs-reliability call.

## 5. With 2 more weeks

- Voice: cloned voice (ElevenLabs) of my actual voice; speculative tool
  prefetch (start RAG retrieval from interim transcripts); WebRTC chat-to-voice
  handoff on the same persona.
- RAG: hybrid BM25+dense retrieval with reranking; nightly GitHub re-ingestion;
  per-claim citation rendering in chat.
- Evals: CI-gated eval runs on every prompt change; automated voice eval rig
  (TTS-generated caller + scripted dialogues over SIP) replacing manual call logs.
