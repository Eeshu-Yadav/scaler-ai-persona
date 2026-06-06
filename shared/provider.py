"""Gemini provider configuration — the sole LLM/embeddings provider.

Gemini exposes an OpenAI-compatible endpoint, so the stack talks to it through
the `openai` client library (that package is just the HTTP transport — there is
no OpenAI account or key anywhere in this project; Google documents this exact
usage). Call configure_provider() once at every entry point after load_dotenv().
"""

import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

MODEL_DEFAULTS = {
    "CHAT_MODEL": "gemini-2.5-flash",
    "VOICE_MODEL": "gemini-2.5-flash",
    "JUDGE_MODEL": "gemini-2.5-pro",
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
