"""Ollama client resilience: a transient 5xx / dropped connection on the first hit
(e.g. a model swap under VRAM pressure) is retried once before failing — so a single
blip doesn't surface as a hard error to the user. 4xx is NOT retried."""
import httpx
import pytest

from app.modules.ai import llm


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)


def _resp(status, body):
    req = httpx.Request("POST", "http://x/api/chat")
    return httpx.Response(status, json=body, request=req)


def test_retries_once_on_transient_5xx(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return _resp(500, {"error": "load failed"}) if len(calls) == 1 \
            else _resp(200, {"message": {"content": "recovered"}})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "hi"}])["content"] == "recovered"
    assert len(calls) == 2  # failed once, retried, succeeded


def test_retries_on_dropped_connection(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return _resp(200, {"embedding": [0.1, 0.2, 0.3]})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.embed("hello") == [0.1, 0.2, 0.3]
    assert len(calls) == 2


def test_does_not_retry_client_error(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return _resp(400, {"error": "bad request"})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1  # 4xx is not transient — fail fast, no retry


def test_gives_up_after_retry_budget(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _resp(503, {"error": "still down"})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        llm.embed("hello")  # both attempts 5xx -> raises (caller turns it into a graceful msg)
