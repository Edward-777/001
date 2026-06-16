"""Thin Ollama client (AI-AGENT §1). Uses the native /api/chat endpoint, which
supports tool-calling for Qwen2.5. The model is swappable via settings."""
from __future__ import annotations

import time

import httpx

from ...core.config import settings


def _post(url: str, payload: dict, *, timeout: float, retries: int = 1) -> httpx.Response:
    """POST to Ollama with a small retry. A model swap under VRAM pressure can make
    llama-server return a transient 5xx (or drop the connection) on the first hit;
    one retry after a short backoff recovers the common case instead of surfacing a
    hard failure to the user. Non-transient errors (4xx) are raised immediately."""
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=timeout)
        except httpx.TransportError:
            if attempt >= retries:
                raise
            time.sleep(1.0)
            continue
        # Retry only transient server-side 5xx; a 4xx is our bug — fail fast below.
        if resp.status_code >= 500 and attempt < retries:
            time.sleep(1.0)
            continue
        resp.raise_for_status()
        return resp


def chat(messages: list[dict], *, tools: list[dict] | None = None,
         model: str | None = None, temperature: float = 0.0, timeout: float = 300.0) -> dict:
    """Return the assistant message dict: {role, content, tool_calls?}.

    messages: OpenAI-style [{role, content, ...}].
    tools: OpenAI-style tool schemas (function definitions).
    """
    payload = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",  # keep the model warm in VRAM between turns
        "options": {"temperature": temperature, "num_ctx": settings.ollama_num_ctx},
    }
    if tools:
        payload["tools"] = tools
    resp = _post(f"{settings.ollama_base_url}/api/chat", payload, timeout=timeout)
    return resp.json()["message"]


def vision_chat(prompt: str, images: list[bytes], *, model: str | None = None,
                temperature: float = 0.0, timeout: float = 300.0) -> str:
    """Ask a vision model (qwen2.5-vl) about one or more images (PNG bytes).
    Used to read invoices/documents. Returns the model's text reply."""
    import base64

    payload = {
        "model": model or settings.ollama_vision_model,
        "messages": [{
            "role": "user", "content": prompt,
            "images": [base64.b64encode(im).decode() for im in images],
        }],
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": temperature},
    }
    resp = _post(f"{settings.ollama_base_url}/api/chat", payload, timeout=timeout)
    return resp.json()["message"]["content"]


def embed(text: str, *, model: str | None = None, timeout: float = 180.0) -> list[float]:
    """Embed a single string (RAG, Phase 3) via the embedding model.
    Generous timeout: the first call cold-loads the embedding model into VRAM."""
    resp = _post(
        f"{settings.ollama_base_url}/api/embeddings",
        {"model": model or settings.ollama_embed_model, "prompt": text, "keep_alive": "30m"},
        timeout=timeout,
    )
    return resp.json()["embedding"]
