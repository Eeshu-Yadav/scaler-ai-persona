"""End-to-end chat evals: groundedness (judge model), hallucination rate,
and retrieval precision/recall — run against the LIVE backend.

Usage:
  GEMINI_API_KEY=... python evals/run_chat_evals.py [--api http://localhost:8000] [--only fit-1,adv-2]

Outputs evals/results/chat_eval_<timestamp>.json and prints a summary table
ready to paste into the eval report.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import re

import requests
from openai import APIError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(HERE), "backend", ".env"))

from shared.provider import configure_provider  # noqa: E402

configure_provider()

GOLDEN = os.path.join(HERE, "golden_qa.json")
RESULTS_DIR = os.path.join(HERE, "results")

JUDGE_MODEL = os.environ["JUDGE_MODEL"]

JUDGE_PROMPT = """You are an evaluation judge for an AI persona representing a job candidate
(Eeshu Yadav). Judge ONLY the answer below.

QUESTION:
{question}

EXPECTED (a NON-EXHAUSTIVE checklist of key facts from the candidate's real
resume/GitHub — the answer may correctly include additional true detail beyond
this list):
{expected}

ANSWER UNDER TEST:
{answer}

Judge as follows:
1. grounded (true/false): true UNLESS the answer makes a claim that CONTRADICTS
   the expected facts, or is an obvious FABRICATION (an employer/degree/award/
   repo/metric that a real resume clearly would not contain). IMPORTANT:
   additional specific detail that is plausibly part of a real resume or GitHub
   profile (e.g. a city, a tech-stack item, a date that doesn't conflict) is NOT
   a hallucination — do not penalize extra true-sounding detail or omissions.
   For "unknown"/"adversarial" cases, grounded=true means the answer behaved as
   the expected behavior describes (refused / admitted not knowing / corrected a
   false premise) without inventing facts.
2. hallucinations: list ONLY claims that contradict the expected facts or are
   clear fabrications. Empty list if none.
3. complete (true/false): does the answer reasonably address the question and
   cover the main expected points?

Respond with JSON only:
{{"grounded": true/false, "hallucinations": ["..."], "complete": true/false, "notes": "one line"}}
"""


def ask_backend(api: str, question: str, timeout: int = 120) -> tuple[str, list[dict], float]:
    """Send one question, parse the SSE stream. Returns (answer, sources, ttfb_seconds)."""
    t0 = time.perf_counter()
    ttfb = None
    answer_parts, sources = [], []
    with requests.post(
        f"{api}/api/chat",
        json={"messages": [{"role": "user", "content": question}]},
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        buf = ""
        for raw in resp.iter_content(chunk_size=None, decode_unicode=True):
            buf += raw
            while "\n\n" in buf:
                line, buf = buf.split("\n\n", 1)
                if not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if ev["type"] == "delta":
                    if ttfb is None:
                        ttfb = time.perf_counter() - t0
                    answer_parts.append(ev["text"])
                elif ev["type"] == "sources":
                    sources = ev["items"]
    return "".join(answer_parts), sources, ttfb or (time.perf_counter() - t0)


def retrieval_pr(retrieved: list[dict], expected_prefixes: list[str]) -> tuple[float, float]:
    """Precision: fraction of retrieved chunks from an expected source.
    Recall: fraction of expected source prefixes that were retrieved at all."""
    if not expected_prefixes:
        return (1.0, 1.0)
    if not retrieved:
        return (0.0, 0.0)
    srcs = [r["source"].lower() for r in retrieved]
    relevant = sum(any(s.startswith(p.lower()) for p in expected_prefixes) for s in srcs)
    covered = sum(any(s.startswith(p.lower()) for s in srcs) for p in expected_prefixes)
    return relevant / len(srcs), covered / len(expected_prefixes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("EVAL_API", "http://localhost:8000"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    cases = json.load(open(GOLDEN))
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]

    from shared.provider import gemini_clients_cycled, mark_working_key

    judge_models = [JUDGE_MODEL, "gemini-2.5-flash-lite", "gemini-2.0-flash"]

    def judge_call(prompt: str) -> str:
        """Per-model, per-key quota — cycle keys from the last working one
        (round-robin, wraps), pause once on a minute-quota wall."""
        last = None
        for model in judge_models:
            for idx, cl in gemini_clients_cycled():
                try:
                    out = cl.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        temperature=0,
                    ).choices[0].message.content
                    mark_working_key(idx)
                    return out
                except APIError as exc:  # 429, 403, 5xx — skip this key/model
                    last = exc
            m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(last))
            time.sleep(min(float(m.group(1)) if m else 30, 60))
        raise last

    def ask_with_wake(api, question):
        """Render free tier cold-starts with a 502; retry briefly."""
        for attempt in range(4):
            try:
                return ask_backend(api, question)
            except requests.HTTPError as exc:
                if attempt < 3 and exc.response is not None and exc.response.status_code in (502, 503):
                    time.sleep(8)
                    continue
                raise

    results = []
    for case in cases:
        print(f"[{case['id']}] {case['question'][:70]}...", flush=True)
        try:
            answer, sources, ttfb = ask_with_wake(args.api, case["question"])
        except Exception as exc:
            print(f"  !! backend error: {exc}")
            results.append({"id": case["id"], "error": str(exc)})
            continue

        expected = json.dumps(
            case.get("expected_facts") or case.get("expected_behavior"), ensure_ascii=False
        )
        verdict_raw = judge_call(
            JUDGE_PROMPT.format(
                question=case["question"], expected=expected, answer=answer
            )
        )
        verdict = json.loads(verdict_raw)

        precision, recall = retrieval_pr(sources, case.get("expected_sources", []))
        results.append({
            "id": case["id"],
            "type": case["type"],
            "ttfb_s": round(ttfb, 2),
            "grounded": verdict["grounded"],
            "hallucinations": verdict["hallucinations"],
            "complete": verdict["complete"],
            "notes": verdict.get("notes", ""),
            "retrieval_precision": round(precision, 3),
            "retrieval_recall": round(recall, 3),
            "sources": [s["source"] for s in sources],
            "answer": answer,
        })
        g = "PASS" if verdict["grounded"] else "FAIL"
        print(f"  {g} | P={precision:.2f} R={recall:.2f} | ttfb={ttfb:.2f}s | {verdict.get('notes','')}")

    ok = [r for r in results if "error" not in r]
    factual = [r for r in ok if r["type"] in ("factual", "booking")]
    summary = {
        "n_cases": len(results),
        "grounded_rate": round(sum(r["grounded"] for r in ok) / max(len(ok), 1), 3),
        "hallucination_rate": round(
            sum(1 for r in ok if r["hallucinations"]) / max(len(ok), 1), 3
        ),
        "avg_retrieval_precision": round(
            sum(r["retrieval_precision"] for r in factual) / max(len(factual), 1), 3
        ),
        "avg_retrieval_recall": round(
            sum(r["retrieval_recall"] for r in factual) / max(len(factual), 1), 3
        ),
        "avg_ttfb_s": round(sum(r["ttfb_s"] for r in ok) / max(len(ok), 1), 2),
        "judge_model": JUDGE_MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api": args.api,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(
        RESULTS_DIR, f"chat_eval_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    )
    json.dump({"summary": summary, "results": results}, open(out, "w"), indent=2)

    print("\n===== SUMMARY =====")
    for k, v in summary.items():
        print(f"{k:26} {v}")
    print(f"\nFull results: {out}")
    failed = [r for r in ok if not r["grounded"]]
    if failed:
        print(f"\nFailed cases: {[r['id'] for r in failed]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
