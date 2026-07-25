"""Agent memory — preferences remembered across conversations: deterministic
writes (audited tool), prompt injection on every turn, revocable."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, auth  # noqa: F401  register
from app.modules.ai import agent, memory
from app.modules.ai.registry import registry
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


def test_remember_tool_stores_and_dedupes(session, user):
    out = registry.execute("remember_preference",
                           {"fact": "Prefers net15 terms for new vendors"},
                           session=session, user=user)["result"]
    assert out["remembered"] == "Prefers net15 terms for new vendors"
    registry.execute("remember_preference",
                     {"fact": "Prefers net15 terms for new vendors"},
                     session=session, user=user)
    assert len(memory.list_for_user(session, user.id)) == 1


def test_memory_is_injected_into_system_prompt(session, user):
    memory.remember(session, user.id, "Values inventory at moving average")

    seen = {}

    def fake_chat(messages, tools=None):
        seen["messages"] = messages
        return {"role": "assistant", "content": "ok"}

    agent.run(session, user, "hello", chat=fake_chat)
    sys_text = " ".join(m["content"] for m in seen["messages"] if m["role"] == "system")
    assert "moving average" in sys_text
    assert "Remembered preferences" in sys_text


def test_no_memory_no_extra_system_block(session, user):
    seen = {}

    def fake_chat(messages, tools=None):
        seen["messages"] = messages
        return {"role": "assistant", "content": "ok"}

    agent.run(session, user, "hello", chat=fake_chat)
    assert not any("Remembered preferences" in m["content"]
                   for m in seen["messages"] if m["role"] == "system")


def test_forget_removes_matching_memories(session, user):
    memory.remember(session, user.id, "Prefers net15 terms")
    memory.remember(session, user.id, "Ship via FedEx when possible")
    out = registry.execute("forget_preference", {"about": "net15"},
                           session=session, user=user)["result"]
    assert out["forgotten"] == 1
    facts = [m.fact for m in memory.list_for_user(session, user.id)]
    assert facts == ["Ship via FedEx when possible"]


def test_memories_are_per_user(session, user):
    other = auth_svc.create_user(session, name="Other", email="o@x", password="pw")
    memory.remember(session, user.id, "Secret preference")
    assert memory.list_for_user(session, other.id) == []


def test_cap_keeps_newest(session, user):
    for i in range(35):
        memory.remember(session, user.id, f"fact {i}")
    facts = [m.fact for m in memory.list_for_user(session, user.id)]
    assert len(facts) == 30
    assert "fact 34" in facts[0] and "fact 0" not in facts
