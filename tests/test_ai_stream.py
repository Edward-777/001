"""Live progress streaming (v2 SSE): the agent reports plan/step/tool events to
an observer as it works, and /assistant/message/stream relays them as SSE with
a final server-rendered bubble. Observers are best-effort and never affect
execution."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.modules import ai, approval, auth, hr  # noqa: F401  register tables
from app.modules.ai import agent
from app.modules.auth import service as auth_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def user(session):
    return auth_svc.create_user(session, name="Emp", email="e@x", password="pw")


class ScriptedChat:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, messages, tools=None):
        return self.responses.pop(0)


# ---- agent event emission ---------------------------------------------------

def test_plain_loop_emits_tool_events(session, user):
    chat = ScriptedChat([
        {"content": "", "tool_calls": [
            {"function": {"name": "nonexistent_tool", "arguments": {}}}]},
        {"content": "That tool does not exist."},
    ])
    events = []
    out = agent.run(session, user, "check something", chat=chat,
                    on_event=events.append)
    assert out["reply"] == "That tool does not exist."
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_start", "tool"]
    assert events[0]["tool"] == "nonexistent_tool"
    assert events[1]["ok"] is False and isinstance(events[1]["ms"], int)


def test_plan_path_emits_plan_step_and_composing_events(session, user):
    chat = ScriptedChat([
        {"content": '{"steps": ["Look up the stock", "Summarize the position"]}'},
        {"content": "Stock is 90 units."},
        {"content": "Position is healthy."},
        {"content": "Stock is 90 units and the position is healthy."},
    ])
    events = []
    out = agent.run(session, user,
                    "Check the widget stock and then summarize our inventory position",
                    chat=chat, on_event=events.append)
    assert [s["status"] for s in out["plan"]] == ["done", "done"]
    assert events[0] == {"type": "plan",
                         "steps": ["Look up the stock", "Summarize the position"]}
    step_events = [(e["index"], e["status"]) for e in events if e["type"] == "step"]
    assert step_events == [(0, "running"), (0, "done"), (1, "running"), (1, "done")]
    assert events[-1]["type"] == "composing"


def test_failed_step_emits_failed_and_skipped(session, user):
    exhaust = {"content": "", "tool_calls": [
        {"function": {"name": "nonexistent_tool", "arguments": {}}}]}
    chat = ScriptedChat([
        {"content": '{"steps": ["Step A", "Step B", "Step C"]}'},
        *[exhaust] * 6,
        {"content": "Step A could not be completed."},
    ])
    events = []
    agent.run(session, user, "Do A and then B and then C for the report",
              chat=chat, on_event=events.append)
    step_events = [(e["index"], e["status"]) for e in events if e["type"] == "step"]
    assert step_events == [(0, "running"), (0, "failed"), (1, "skipped"), (2, "skipped")]


def test_broken_observer_never_breaks_the_turn(session, user):
    def boom(event):
        raise RuntimeError("observer crashed")
    chat = ScriptedChat([
        {"content": "", "tool_calls": [
            {"function": {"name": "nonexistent_tool", "arguments": {}}}]},
        {"content": "All good."},
    ])
    out = agent.run(session, user, "check something", chat=chat, on_event=boom)
    assert out["reply"] == "All good."


# ---- SSE web route ----------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app.main import app
    from app.web import ai_routes

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as s:
        auth_svc.create_user(s, name="Emp", email="e@x", password="pw")
        s.commit()

    def override():
        s = TestSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    # the stream worker thread opens its own session — point it at the test DB
    monkeypatch.setattr(ai_routes, "_worker_session", TestSession)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _sse_events(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):])
            for line in text.splitlines() if line.startswith("data: ")]


def test_stream_route_relays_events_and_final_bubble(client, monkeypatch):
    from app.modules.ai import llm
    monkeypatch.setattr(llm, "chat",
                        lambda messages, tools=None: {"content": "hi from the model"})
    client.post("/login", data={"email": "e@x", "password": "pw"})

    r = client.post("/assistant/message/stream", data={"message": "hello there"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(r.text)
    assert events[-1]["type"] == "final"
    assert "hi from the model" in events[-1]["html"]

    # the turn was persisted like a normal (non-stream) message
    page = client.get("/assistant")
    assert "hello there" in page.text
    assert "hi from the model" in page.text


def test_stream_route_reports_llm_failure_in_final(client, monkeypatch):
    from app.modules.ai import llm

    def down(messages, tools=None):
        raise ConnectionError("ollama down")
    monkeypatch.setattr(llm, "chat", down)
    client.post("/login", data={"email": "e@x", "password": "pw"})

    r = client.post("/assistant/message/stream", data={"message": "hello there"})
    events = _sse_events(r.text)
    assert events[-1]["type"] == "final"
    assert "Assistant unavailable" in events[-1]["html"]

    # nothing persisted on failure
    page = client.get("/assistant")
    assert "hello there" not in page.text
