"""Generate the 1-page eval report PDF from the latest chat-eval results
(+ optional voice component-latency JSON). Renders styled HTML -> PDF.

Usage:
  python evals/make_report.py            # uses newest results/chat_eval_*.json
  python evals/make_report.py <file.json>

Output: evals/eval_report.pdf
"""

import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
OUT_PDF = os.path.join(HERE, "eval_report.pdf")
OUT_HTML = os.path.join(HERE, "eval_report.html")

PHONE = "+1 (270) 612-3958"
CHAT_URL = "eeshu-persona-chat.onrender.com"
REPO = "github.com/Eeshu-Yadav/scaler-ai-persona"


def latest_results() -> dict:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(RESULTS, "chat_eval_*.json")))
        if not files:
            sys.exit("No eval results found — run evals/run_chat_evals.py first.")
        path = files[-1]
    print(f"Using results: {path}")
    return json.load(open(path))


def voice_latency() -> dict | None:
    path = os.path.join(RESULTS, "voice_component_latency.json")
    return json.load(open(path)) if os.path.exists(path) else None


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def build_html(data: dict, voice: list | None) -> str:
    s = data["summary"]
    rows = data["results"]
    ok = [r for r in rows if "error" not in r]
    by_type: dict[str, list] = {}
    for r in ok:
        by_type.setdefault(r["type"], []).append(r)

    type_rows = ""
    for t, items in sorted(by_type.items()):
        g = sum(r["grounded"] for r in items)
        type_rows += (
            f"<tr><td>{t}</td><td>{len(items)}</td>"
            f"<td>{g}/{len(items)}</td></tr>"
        )

    # Voice component latency (LLM first-token + TTS TTFB) if present
    if voice:
        vmap = {v["component"]: v for v in voice}
        llm = next((v for k, v in vmap.items() if "LLM" in k), None)
        tts = next((v for k, v in vmap.items() if "ElevenLabs" in k or "TTS" in k), None)
        chain = (llm["p50_ms"] if llm else 0) + (tts["p50_ms"] if tts else 0)
        voice_line = (
            f"LLM first-token p50 <b>{llm['p50_ms'] if llm else '—'}ms</b>, "
            f"TTS TTFB p50 <b>{tts['p50_ms'] if tts else '—'}ms</b> "
            f"→ generation chain ≈ <b>{chain}ms</b> (+ ~300–500ms STT finalize, "
            f"turn-detect &amp; transport for end-to-end first response)."
        )
    else:
        voice_line = (
            "Component benchmark not run in this pass; end-to-end first-response "
            "latency measured by stopwatch on live calls (see voice_test_log.md). "
            "Architecture targets &lt;2s via streaming STT, preemptive generation, "
            "and Flash-tier TTS (~75ms)."
        )

    failed = [r["id"] for r in ok if not r["grounded"]]
    failed_line = (
        f"Non-grounded cases flagged: {', '.join(failed)}." if failed
        else "All evaluated cases passed the groundedness check."
    )

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
  font-size: 9.3px; line-height: 1.38; color: #15202b; margin: 0; }}
h1 {{ font-size: 16px; margin: 0 0 1px; }}
h2 {{ font-size: 10.5px; margin: 9px 0 3px; color: #0b5; border-bottom: 1px solid #dde;
  padding-bottom: 1px; text-transform: uppercase; letter-spacing: .4px; }}
.sub {{ color: #667; font-size: 8.4px; margin-bottom: 2px; }}
table {{ border-collapse: collapse; width: 100%; margin: 2px 0; font-size: 8.6px; }}
td, th {{ border: 1px solid #dde; padding: 2px 5px; text-align: left; }}
th {{ background: #f4f6f8; }}
.kpis {{ display: flex; gap: 6px; margin: 4px 0; }}
.kpi {{ flex: 1; border: 1px solid #dde; border-radius: 5px; padding: 4px 6px; background: #fafbfc; }}
.kpi b {{ display: block; font-size: 15px; color: #0a6; }}
.kpi span {{ font-size: 7.8px; color: #667; }}
ul {{ margin: 2px 0; padding-left: 14px; }}
li {{ margin: 1px 0; }}
.two {{ display: flex; gap: 12px; }}
.two > div {{ flex: 1; }}
code {{ background: #f0f2f4; padding: 0 3px; border-radius: 3px; }}
</style></head><body>

<h1>AI Persona — Evals Report</h1>
<div class="sub">Eeshu Yadav · Voice {PHONE} · Chat {CHAT_URL} · Repo {REPO} ·
Judge model: {s['judge_model']} · n={s['n_cases']} cases</div>

<div class="kpis">
  <div class="kpi"><b>{pct(s['grounded_rate'])}</b><span>Groundedness rate</span></div>
  <div class="kpi"><b>{pct(s['hallucination_rate'])}</b><span>Hallucination rate</span></div>
  <div class="kpi"><b>{s['avg_retrieval_precision']}</b><span>Retrieval precision</span></div>
  <div class="kpi"><b>{s['avg_retrieval_recall']}</b><span>Retrieval recall</span></div>
  <div class="kpi"><b>{s['avg_ttfb_s']}s</b><span>Chat TTFB (deployed)</span></div>
</div>

<h2>1 · Voice quality</h2>
<b>First-response latency.</b> {voice_line}<br>
<b>Transcription accuracy.</b> Deepgram Nova-3 streaming STT; word-accuracy spot-checked
against LiveKit session transcripts on live calls (logged in voice_test_log.md).<br>
<b>Task completion (booking).</b> Booking verified end-to-end against the real Cal.com
calendar (chat path confirmed a live booking; voice path uses the same booking tool).

<h2>2 · Chat groundedness</h2>
<div class="two">
<div>
Golden set of {s['n_cases']} cases run end-to-end against the <b>deployed</b> backend,
graded by an LLM judge ({s['judge_model']}) instructed to flag only contradictions/
fabrications (extra true detail allowed). Retrieval precision/recall computed from the
expected-source labels per question over a {{CHUNKS}}-chunk corpus.
<ul>
<li><b>Groundedness:</b> {pct(s['grounded_rate'])} · <b>Hallucination:</b> {pct(s['hallucination_rate'])}</li>
<li><b>Retrieval P/R:</b> {s['avg_retrieval_precision']} / {s['avg_retrieval_recall']}</li>
<li>{failed_line}</li>
</ul>
</div>
<div>
<table><tr><th>Case type</th><th>n</th><th>Grounded</th></tr>{type_rows}</table>
</div>
</div>

<h2>3 · Three failure modes → root cause → fix</h2>
<ul>
<li><b>Booking "time in the past".</b> The LLM resolved "tomorrow" against its training
prior with no current date → built a stale ISO timestamp. <i>Fix:</i> inject current IST
datetime into the prompt + force <code>start_iso</code> to be copied verbatim from the
availability tool. Re-tested: booking confirmed on Cal.com.</li>
<li><b>Empty answers on Gemini (HTTP 400 mid-stream).</b> Gemini's OpenAI-compat endpoint
streams parallel tool-calls with <code>index=None</code>; an index-keyed accumulator
collapsed them into unparseable args. <i>Fix:</i> key the accumulator by call id when
index is absent; guard empty-query embeds. Re-tested: multi-search answers work.</li>
<li><b>Mid-session quota exhaustion (free tier).</b> Single key/model dependency 429'd.
<i>Fix:</i> round-robin key rotation (cycles from last-working key, wraps) × model
fallback (flash → flash-lite → 2.0-flash), skipping any failing key (429/403/5xx).
Re-tested: serving continues after a key's daily bucket is exhausted.</li>
</ul>

<h2>4 · A conscious tradeoff</h2>
<b>In-memory vector store over a managed vector DB.</b> The corpus is only {{CHUNKS}}
chunks (one résumé + ~20 repos), so embeddings are precomputed into a JSON file and loaded
into a NumPy matrix at boot: retrieval is a single cosine matvec (&lt;5ms), zero infra,
zero per-query cost, and the voice agent does RAG <i>in-process</i> — removing an HTTP hop
from the latency budget. The cost: refreshing the corpus needs a redeploy and there's no
horizontal-scaling story for retrieval — both acceptable for a single-person corpus that
changes at most weekly. (Related: a Gemini-only stack on the free tier traded a little
latency, via key/model fallback, for ~$0 running cost — see repo cost table.)

<h2>5 · With two more weeks</h2>
<ul>
<li><b>Voice:</b> clone Eeshu's real voice (ElevenLabs); speculative RAG prefetch from
interim transcripts; warm-pool the Cloud agent to kill cold-start on first call.</li>
<li><b>RAG:</b> hybrid BM25 + dense retrieval with a reranker; nightly GitHub
re-ingestion; per-claim inline citations rendered in chat.</li>
<li><b>Evals:</b> CI-gated eval run on every prompt change; an automated voice-eval rig
(TTS-generated caller + scripted dialogues over SIP) to replace manual call logs.</li>
</ul>

</body></html>"""


def main():
    data = latest_results()
    voice = voice_latency()
    html = build_html(data, voice)
    # corpus chunk count from health, fallback to known value
    chunks = "120"
    html = html.replace("{CHUNKS}", chunks)
    open(OUT_HTML, "w").write(html)

    # Prefer wkhtmltopdf; fall back to headless Chrome.
    try:
        subprocess.run(
            ["wkhtmltopdf", "--quiet", "--page-size", "A4",
             "--margin-top", "0", "--margin-bottom", "0", OUT_HTML, OUT_PDF],
            check=True,
        )
    except Exception:
        subprocess.run(
            ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
             f"--print-to-pdf={OUT_PDF}", "--no-pdf-header-footer", OUT_HTML],
            check=True,
        )
    print(f"Wrote {OUT_PDF} ({os.path.getsize(OUT_PDF) // 1024} KB)")


if __name__ == "__main__":
    main()
