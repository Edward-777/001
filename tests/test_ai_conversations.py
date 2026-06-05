"""Phase 2c — conversation persistence + memory + review permissions."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai  # noqa: F401  registers ai tables
from app.modules.ai import agent
from app.modules.ai import conversations as convo
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def user(session):
    return auth_svc.create_user(session, name="U", email="u@x", password="pw")


def test_history_preserves_order(session, user):
    conv = convo.start_new(session, user.id)
    convo.add_message(session, conv, "user", "how much stock?")
    convo.add_message(session, conv, "assistant", "100 widgets")
    h = convo.history_for_llm(session, conv.id)
    assert [m["role"] for m in h] == ["user", "assistant"]
    assert h[0]["content"] == "how much stock?"
    assert h[1]["content"] == "100 widgets"


def test_first_user_message_sets_title(session, user):
    conv = convo.start_new(session, user.id)
    convo.add_message(session, conv, "user", "Order more chairs please")
    assert conv.title == "Order more chairs please"


def test_agent_injects_history_as_memory(session, user):
    """The agent must re-send prior turns so '그거' can resolve."""
    seen = {}

    def fake_chat(messages, tools=None):
        seen["messages"] = list(messages)  # snapshot (agent mutates the list after)
        return {"content": "ok"}

    history = [{"role": "user", "content": "stock of WIDGET-1?"},
               {"role": "assistant", "content": "100 on hand"}]
    agent.run(session, user, "order 50 more of those", history=history, chat=fake_chat)

    contents = [m.get("content") for m in seen["messages"]]
    assert "stock of WIDGET-1?" in contents   # memory present
    assert "100 on hand" in contents
    # new msg last; a short language tag is appended to the user turn (overrides
    # history-induced language drift) so it starts with — not equals — the message.
    last = seen["messages"][-1]
    assert last["role"] == "user" and last["content"].startswith("order 50 more of those")


def test_review_permissions(session):
    admin = auth_svc.create_user(session, name="Admin", email="a@x", password="pw", role=Role.ADMIN)
    alice = auth_svc.create_user(session, name="Alice", email="al@x", password="pw")
    bob = auth_svc.create_user(session, name="Bob", email="b@x", password="pw")
    conv = convo.start_new(session, alice.id)

    assert convo.get_conversation(session, conv.id, alice) is not None   # owner
    assert convo.get_conversation(session, conv.id, admin) is not None   # admin audit
    assert convo.get_conversation(session, conv.id, bob) is None         # other employee denied


def test_long_conversation_folds_into_summary(session, user, monkeypatch):
    """Once a chat grows past the window, older turns fold into a rolling summary
    so memory scales without re-sending everything."""
    from app.modules.ai import llm
    monkeypatch.setattr(llm, "chat", lambda messages, **kw: {"content": "SUMMARY: widgets discussed"})

    conv = convo.start_new(session, user.id)
    for i in range(convo._WINDOW + 5):
        convo.add_message(session, conv, "user", f"message number {i}")

    hist = convo.history_for_llm(session, conv.id)
    assert hist[0]["role"] == "system" and "SUMMARY" in hist[0]["content"]   # summary first
    assert len(hist) == 1 + convo._WINDOW                                      # summary + window
    assert conv.summary and "SUMMARY" in conv.summary
    assert conv.summarized_upto_id > 0


def test_list_scopes_by_role(session):
    admin = auth_svc.create_user(session, name="Admin", email="a2@x", password="pw", role=Role.ADMIN)
    alice = auth_svc.create_user(session, name="Alice", email="al2@x", password="pw")
    convo.start_new(session, alice.id)
    convo.start_new(session, admin.id)

    assert len(convo.list_conversations(session, alice)) == 1   # only her own
    assert len(convo.list_conversations(session, admin)) == 2   # all (audit)
