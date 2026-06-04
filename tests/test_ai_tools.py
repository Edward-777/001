"""Phase 2d — expanded toolset: input validation (no premature records),
expense-vs-purchase routing, and permission inheritance on the new finance tools."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai  # noqa: F401  register tables + tools
from app.modules.ai import agent
from app.modules.ai.registry import registry
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def employee(session):
    return auth_svc.create_user(session, name="Emp", email="e@x", password="pw")


def test_purchase_request_requires_amounts(session, employee):
    """Missing price -> the tool refuses and asks, instead of creating a $0 record."""
    out = registry.execute("create_purchase_request", {"title": "laptop"},
                           session=session, user=employee)
    assert "error" in out["result"]
    assert "unit_price" in out["result"]["error"]


def test_expense_request_routes_to_expense_not_purchase(session, employee):
    out = registry.execute("create_expense_request",
                           {"title": "SD trip", "amount": 1200, "kind": "trip"},
                           session=session, user=employee)
    res = out["result"]
    assert res["type"] == "trip"
    assert res["total_amount"] == "1200.00"


def test_finance_tools_inherit_permissions(session, employee):
    admin = auth_svc.create_user(session, name="Admin", email="a@x", password="pw", role=Role.ADMIN)
    # employee (finance level 1) is not even offered the GL tools...
    names = {t["function"]["name"] for t in registry.schemas_for(employee)}
    assert "get_trial_balance" not in names
    assert "get_ap_aging" not in names
    # ...and a forced call is denied at execution (defense in depth)
    out = registry.execute("get_trial_balance", {}, session=session, user=employee)
    assert "permission denied" in out["error"]
    # admin (finance 3) is offered them
    assert "get_trial_balance" in {t["function"]["name"] for t in registry.schemas_for(admin)}


def test_employee_can_see_own_requests_tool(session, employee):
    names = {t["function"]["name"] for t in registry.schemas_for(employee)}
    assert "list_my_requests" in names          # own data — no scope needed
    assert "create_expense_request" in names    # anyone can submit their own expense


def test_recovers_tool_call_emitted_as_text(session, employee):
    """Qwen sometimes writes the call as JSON text; the agent must execute it, not
    leak the raw JSON to the user."""
    turns = [
        {"content": '{"name": "list_my_requests", "arguments": {}}'},  # call-as-text
        {"content": "You have no open requests."},                      # final reply
    ]
    out = agent.run(session, employee, "show my requests", chat=lambda m, tools=None: turns.pop(0))
    assert [t["tool"] for t in out["tool_calls"]] == ["list_my_requests"]
    assert out["reply"] == "You have no open requests."  # raw JSON not leaked


def test_normal_prose_is_not_mistaken_for_a_tool_call(session, employee):
    out = agent.run(session, employee, "hi", chat=lambda m, tools=None: {"content": "Hello!"})
    assert out["reply"] == "Hello!"
    assert out["tool_calls"] == []


def test_recovers_tool_call_wrapped_in_tags_and_garbage(session, employee):
    """Qwen sometimes wraps the call in <tool_call> tags with stray leading tokens."""
    turns = [
        {"content": ' iNdEx\n{"name": "list_my_requests", "arguments": {}}\n</tool_call>'},
        {"content": "Here you go."},
    ]
    out = agent.run(session, employee, "my requests?", chat=lambda m, tools=None: turns.pop(0))
    assert [t["tool"] for t in out["tool_calls"]] == ["list_my_requests"]
    assert out["reply"] == "Here you go."
