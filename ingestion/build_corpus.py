"""Build the RAG corpus: resume + live GitHub data → data/corpus.json.

Sources:
  1. ingestion/sources/resume.md       — chunked by section
  2. GitHub original repos              — description, README, languages, recent commits
  3. GitHub merged PRs (contributions)  — OpenWISP, KMesh, etc. via the search API

Run:  GITHUB_TOKEN=ghp_xxx GEMINI_API_KEY=... python ingestion/build_corpus.py
(GITHUB_TOKEN optional but strongly recommended — unauthenticated search rate
limits are tiny.)
"""

import base64
import json
import os
import re
import sys
import time

import requests
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.provider import configure_provider  # noqa: E402

GITHUB_USER = "Eeshu-Yadav"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "data", "corpus.json")
RESUME_PATH = os.path.join(ROOT, "ingestion", "sources", "resume.md")

# Original repos worth indexing even if undescribed; profile/junk repos to skip.
SKIP_REPOS = {".github", "Eeshu-Yadav", "Eeshu-Yadav.github.io-portfolio_old", "android_app"}
MAX_CHUNK_CHARS = 1800
MAX_README_CHARS = 12000


def gh(url: str, **params) -> requests.Response:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        print("Rate limited; sleeping 60s...", file=sys.stderr)
        time.sleep(60)
        return gh(url, **params)
    return r


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries, packing up to max_chars per chunk."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 > max_chars and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def resume_chunks() -> list[dict]:
    """Chunk the resume by ## sections, keeping each section whole when possible."""
    text = open(RESUME_PATH).read()
    sections = re.split(r"\n(?=## )", text)
    out = []
    for sec in sections:
        title_match = re.match(r"#+ (.+)", sec)
        title = title_match.group(1).strip() if title_match else "Resume"
        for i, chunk in enumerate(chunk_text(sec)):
            out.append(
                {"source": "resume", "title": f"Resume — {title}", "text": chunk}
            )
    return out


def github_repo_chunks() -> list[dict]:
    out = []
    repos = []
    page = 1
    while True:
        r = gh(
            f"https://api.github.com/users/{GITHUB_USER}/repos",
            per_page=100, page=page, sort="updated",
        )
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    originals = [
        r for r in repos
        if not r["fork"] and r["name"] not in SKIP_REPOS and r.get("size", 0) > 0
    ]
    print(f"Indexing {len(originals)} original repos...")

    for repo in originals:
        name = repo["name"]
        parts = [f"GitHub repository: {GITHUB_USER}/{name}"]
        if repo.get("description"):
            parts.append(f"Description: {repo['description']}")

        langs = gh(repo["languages_url"]).json()
        if isinstance(langs, dict) and langs:
            total = sum(langs.values()) or 1
            lang_str = ", ".join(
                f"{k} ({v * 100 // total}%)" for k, v in
                sorted(langs.items(), key=lambda x: -x[1])
            )
            parts.append(f"Languages: {lang_str}")

        # README
        readme = gh(f"https://api.github.com/repos/{GITHUB_USER}/{name}/readme")
        if readme.status_code == 200:
            content = base64.b64decode(readme.json()["content"]).decode("utf-8", "replace")
            parts.append(f"README:\n{content[:MAX_README_CHARS]}")

        # Recent commit messages (design/history evidence)
        commits = gh(
            f"https://api.github.com/repos/{GITHUB_USER}/{name}/commits", per_page=15
        )
        if commits.status_code == 200:
            msgs = [
                c["commit"]["message"].split("\n")[0]
                for c in commits.json() if isinstance(c, dict)
            ]
            if msgs:
                parts.append("Recent commits: " + " | ".join(msgs))

        full = "\n\n".join(parts)
        for chunk in chunk_text(full):
            out.append({"source": f"github/{name}", "title": f"Repo {name}", "text": chunk})
        time.sleep(0.3)
    return out


def github_contribution_chunks() -> list[dict]:
    """Merged PRs across orgs (OpenWISP, KMesh, ...) — the OSS contribution record."""
    out = []
    r = gh(
        "https://api.github.com/search/issues",
        q=f"author:{GITHUB_USER} is:pr is:merged", per_page=100, sort="updated",
    )
    if r.status_code != 200:
        print(f"PR search failed ({r.status_code}); skipping contributions.", file=sys.stderr)
        return out
    items = r.json().get("items", [])
    print(f"Indexing {len(items)} merged PRs...")
    by_repo: dict[str, list[str]] = {}
    for pr in items:
        repo_full = "/".join(pr["repository_url"].split("/")[-2:])
        body = (pr.get("body") or "").strip()
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)[:600]
        entry = f"PR #{pr['number']}: {pr['title']} (merged {pr['closed_at'][:10]})"
        if body:
            entry += f"\n{body}"
        by_repo.setdefault(repo_full, []).append(entry)
    for repo_full, entries in by_repo.items():
        text = (
            f"Merged open-source pull requests by Eeshu Yadav in {repo_full}:\n\n"
            + "\n\n".join(entries)
        )
        for chunk in chunk_text(text):
            out.append({
                "source": f"contributions/{repo_full}",
                "title": f"Merged PRs in {repo_full}",
                "text": chunk,
            })
    return out


def main():
    provider = configure_provider()
    model = os.environ["EMBEDDING_MODEL"]
    chunks = resume_chunks() + github_repo_chunks() + github_contribution_chunks()
    for i, c in enumerate(chunks):
        c["id"] = i
    print(f"Total chunks: {len(chunks)} — embedding with {model} ({provider})...")

    from openai import RateLimitError

    client = OpenAI()
    embeddings = []
    # Gemini free tier: 100 embed contents/min — pace batches and retry on 429.
    batch_size = 25 if provider == "gemini" else 100
    pause = 16 if provider == "gemini" else 0
    for i in range(0, len(chunks), batch_size):
        batch = [c["text"] for c in chunks[i:i + batch_size]]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(model=model, input=batch)
                break
            except RateLimitError:
                wait = 45 * (attempt + 1)
                print(f"\n  rate limited, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
        else:
            raise SystemExit("embedding kept failing after 5 retries")
        embeddings.extend([d.embedding for d in resp.data])
        print(f"  embedded {min(i + batch_size, len(chunks))}/{len(chunks)}", end="\r", flush=True)
        time.sleep(pause)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"chunks": chunks, "embeddings": embeddings}, f)
    size_mb = os.path.getsize(OUT_PATH) / 1e6
    print(f"Wrote {OUT_PATH} ({size_mb:.1f} MB, {len(chunks)} chunks)")


if __name__ == "__main__":
    main()
