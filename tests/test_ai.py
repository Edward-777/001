"""Phase 2 — AI agent: tool registry, permission inheritance, and the agent
loop (with a fake LLM so the test is deterministic and needs no Ollama)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables + AI tools
    accounting, ai, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.ai import agent
from app.modules.ai.registry import registry
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        approval.service.seed_approval_rules(s)
        yield s


@pytest.fixture
def users(session):
    admin = auth_svc.create_user(session, name="Admin", email="a@x", password="pw", role=Role.ADMIN)
    emp = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")  # employee
    session.flush()
    return {"admin": admin, "emp": emp}


class FakeChat:
    """Scripted assistant messages (one per loop iteration)."""
    def __init__(self, *messages):
        self.messages = list(messages)
        self.i = 0

    def __call__(self, messages, tools=None):
        m = self.messages[self.i]
        self.i += 1
        return m


def _toolcall(name, args):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


# ---- permission inheritance (the headline) ------------------------------

def test_financials_tool_hidden_from_employee(session, users):
    emp_tools = {t["function"]["name"] for t in registry.schemas_for(users["emp"])}
    admin_tools = {t["function"]["name"] for t in registry.schemas_for(users["admin"])}
    assert "get_financials" not in emp_tools     # finance level 3 -> not offered
    assert "get_financials" in admin_tools


def test_employee_cannot_execute_financials_even_if_forced(session, users):
    # adversarial: call the tool directly bypassing the filtered list
    out = registry.execute("get_financials", {"period": "2026-01"},
                           session=session, user=users["emp"])
    assert "error" in out and "permission denied" in out["error"]


def test_admin_can_execute_financials(session, users):
    out = registry.execute("get_financials", {"period": "2026-01"},
                           session=session, user=users["admin"])
    assert out["result"]["period"] == "2026-01"
    assert out["result"]["balanced"] is True


# ---- agent loop ---------------------------------------------------------

def test_agent_runs_tool_then_answers(session, users):
    fake = FakeChat(
        _toolcall("create_purchase_request",
                  {"title": "Buy widgets", "qty": 2, "unit_price": 50}),
        {"role": "assistant", "content": "Created your purchase request."},
    )
    out = agent.run(session, users["emp"], "buy 2 widgets at $50", chat=fake)
    assert out["reply"] == "Created your purchase request."
    assert out["tool_calls"][0]["tool"] == "create_purchase_request"
    assert out["tool_calls"][0]["result"]["result"]["total_amount"] == "100.00"
    # the request really exists
    reqs = approval.service.list_requests_for_user(session, users["emp"].id)
    assert any(r.title == "Buy widgets" for r in reqs)


def test_agent_reads_live_stock(session, users):
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, lines=[{"product_id": p.id, "qty": 7, "unit_cost": 3}])
    inv.post_inbound(session, inb.id)

    fake = FakeChat(
        _toolcall("get_stock", {"sku": "W1"}),
        {"role": "assistant", "content": "You have 7 on hand."},
    )
    out = agent.run(session, users["admin"], "how many W1 in stock?", chat=fake)
    assert out["tool_calls"][0]["result"]["result"]["qty_on_hand"] == "7.000"
    assert out["reply"] == "You have 7 on hand."


def test_agent_tool_error_surfaces_as_data(session, users):
    # employee's model tries financials (denied); agent keeps going to an answer
    fake = FakeChat(
        _toolcall("get_financials", {"period": "2026-01"}),
        {"role": "assistant", "content": "Sorry, you don't have access to financials."},
    )
    out = agent.run(session, users["emp"], "show me the P&L", chat=fake)
    assert "permission denied" in out["tool_calls"][0]["result"]["error"]
    assert "access" in out["reply"]
