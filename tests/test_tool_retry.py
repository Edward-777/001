"""Repeated-failure breaker: a tool that keeps failing in one turn is withdrawn
so the model must answer in text (i.e. ask the user) instead of burning the
iteration limit on fabricated retries."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, hr  # noqa: F401
from app.modules.ai import agent
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
    return auth_svc.create_user(session, name="Emp", email="e@x", password="pw")


class RetryingChat:
    """Keeps calling the same (failing) tool until it stops being offered."""

    def __init__(self):
        self.offered: list[list[str] | None] = []

    def __call__(self, messages, tools=None):
        names = [t["function"]["name"] for t in tools] if tools else None
        self.offered.append(names)
        if names and "create_purchase_request" in names:
            return {"content": "", "tool_calls": [{"function": {
                "name": "create_purchase_request",
                "arguments": {"title": "GPU servers", "qty": 2}}}]}  # no price -> error
        return {"content": "What is the unit price for the servers?"}


class SubstitutingChat:
    """Fails a pay, then tries to 'succeed' with a different money write —
    the live E1 incident (fabricated bank ref on an unrelated instruction)."""

    def __init__(self):
        self.step = 0

    def __call__(self, messages, tools=None):
        self.step += 1
        if self.step == 1:
            return {"content": "", "tool_calls": [{"function": {
                "name": "pay_vendor",
                "arguments": {"bill_no": "BILL-2026-9999", "amount": 500}}}]}
        if self.step == 2:
            return {"content": "", "tool_calls": [{"function": {
                "name": "confirm_payment_executed",
                "arguments": {"instruction_id": 1, "paid_date": "2026-08-04",
                              "payment_ref": "PaymentRef123"}}}]}
        return {"content": "The bill was not found; nothing was recorded."}


def test_failed_money_write_blocks_substitute_money_writes(session):
    """After one money-write tool fails in a turn, a DIFFERENT money-write
    tool is refused (same-tool batch retries stay allowed)."""
    admin = auth_svc.create_user(session, name="Adm", email="a@x", password="pw",
                                 role=Role.ADMIN)
    out = agent.run(session, admin, "Pay vendor bill BILL-2026-9999 for $500.",
                    chat=SubstitutingChat())
    pay = [c for c in out["tool_calls"] if c["tool"] == "pay_vendor"]
    confirm = [c for c in out["tool_calls"]
               if c["tool"] == "confirm_payment_executed"]
    assert pay and not pay[0]["ok"]
    assert confirm and not confirm[0]["ok"]
    assert "blocked" in str(confirm[0]["result"])
    assert "pay_vendor" in str(confirm[0]["result"])


def test_failing_tool_is_withdrawn_and_model_asks(session, user):
    chat = RetryingChat()
    out = agent.run(session, user, "order 2 gpu servers", chat=chat)
    fails = [c for c in out["tool_calls"] if c["tool"] == "create_purchase_request"]
    assert len(fails) == agent._MAX_SAME_TOOL_FAILURES  # capped, not limit-exhausted
    assert all(not c["ok"] for c in fails)
    # after the cap the tool is no longer offered...
    assert "create_purchase_request" not in (chat.offered[-1] or [])
    # ...so the turn ends in a question, not "(stopped: tool-iteration limit reached)"
    assert "unit price" in out["reply"]
