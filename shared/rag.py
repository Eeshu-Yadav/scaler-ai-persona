"""In-memory RAG over the persona corpus.

Design decision: the corpus is small (a few hundred chunks — one resume +
~20 repos worth of READMEs/commits), so we skip a vector DB entirely.
Embeddings are precomputed by ingestion/build_corpus.py into data/corpus.json
and loaded into a numpy matrix at process start. Retrieval is a single
matrix-vector cosine similarity: <5ms, zero infra, zero per-query cost
beyond the query embedding. This keeps the voice agent's tool-call latency
dominated by the embedding API call (~100-150ms), not retrieval.
"""

import json
import os
from functools import lru_cache

import numpy as np
from openai import OpenAI

_DEFAULT_CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "corpus.json"
)


class CorpusStore:
    def __init__(self, corpus_path: str | None = None):
        path = corpus_path or os.environ.get("CORPUS_PATH", _DEFAULT_CORPUS)
        with open(path) as f:
            data = json.load(f)
        self.chunks = data["chunks"]  # [{id, source, title, text}]
        self.matrix = np.array(data["embeddings"], dtype=np.float32)
        # Normalize once so search is a pure dot product.
        self.matrix /= np.linalg.norm(self.matrix, axis=1, keepdims=True)
        self._client = OpenAI()

    def embed_query(self, query: str) -> np.ndarray:
        # configure_provider() (called at every entry point) sets EMBEDDING_MODEL.
        resp = self._client.embeddings.create(
            model=os.environ["EMBEDDING_MODEL"], input=[query]
        )
        v = np.array(resp.data[0].embedding, dtype=np.float32)
        return v / np.linalg.norm(v)

    def search(self, query: str, top_k: int = 5, min_score: float = 0.25) -> list[dict]:
        """Return top_k chunks above min_score, each with its similarity score."""
        q = self.embed_query(query)
        scores = self.matrix @ q
        # The resume is the highest-signal source for career/fit questions;
        # give it a small boost so thin repo chunks don't crowd it out.
        for i, c in enumerate(self.chunks):
            if c["source"] == "resume":
                scores[i] += 0.05
        idx = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in idx:
            if scores[i] < min_score:
                continue
            chunk = dict(self.chunks[int(i)])
            chunk["score"] = round(float(scores[i]), 4)
            results.append(chunk)
        return results

    def format_results(self, results: list[dict]) -> str:
        """Render retrieved chunks as a context block for the LLM."""
        if not results:
            return (
                "NO_RESULTS: nothing in Eeshu's resume or GitHub corpus matches this "
                "query. Say you don't have that information rather than guessing."
            )
        blocks = []
        for r in results:
            blocks.append(f"[source: {r['source']} | {r['title']}]\n{r['text']}")
        return "\n\n---\n\n".join(blocks)


@lru_cache(maxsize=1)
def get_store() -> CorpusStore:
    return CorpusStore()
