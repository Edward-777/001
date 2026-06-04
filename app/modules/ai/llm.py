"""Thin Ollama client (AI-AGENT §1). Uses the native /api/chat endpoint, which
supports tool-calling for Qwen2.5. The model is swappable via settings."""
from __future__ import annotations

import httpx

from ...core.config import settings


def chat(messages: list[dict], *, tools: list[dict] | None = None,
         model: str | None = None, temperature: float = 0.0, timeout: float = 120.0) -> dict:
    """Return the assistant message dict: {role, content, tool_calls?}.

    messages: OpenAI-style [{role, content, ...}].
    tools: OpenAI-style tool schemas (function definitions).
    """
    payload = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",  # keep the model warm in VRAM between turns
        "options": {"temperature": temperature},
    }
    if tools:
        payload["tools"] = tools
    resp = httpx.post(f"{settings.ollama_base_url}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]


def embed(text: str, *, model: str | None = None, timeout: float = 180.0) -> list[float]:
    """Embed a single string (RAG, Phase 3) via the embedding model.
    Generous timeout: the first call cold-loads the embedding model into VRAM."""
    resp = httpx.post(
        f"{settings.ollama_base_url}/api/embeddings",
        json={"model": model or settings.ollama_embed_model, "prompt": text, "keep_alive": "30m"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]
