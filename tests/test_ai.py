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
    assert out["result"]["period_MONTH"] == "2026-01"
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


def test_agent_blocks_submit_in_same_turn_as_draft(session, users):
    """Deterministic maker-checker gate: even if the model tries to create AND submit
    in one turn, the submit is refused — the user must confirm in a separate turn."""
    fake = FakeChat(
        _toolcall("create_purchase_request", {"title": "monitors", "qty": 3, "unit_price": 200}),
        _toolcall("submit_request_for_approval", {"request_no": "REQ-2026-0001"}),
        {"role": "assistant", "content": "Draft created — please confirm the figures."},
    )
    out = agent.run(session, users["emp"], "buy 3 monitors at $200", chat=fake)
    submit = next(t for t in out["tool_calls"] if t["tool"] == "submit_request_for_approval")
    assert "confirmation required" in submit["result"]["error"]
    # the request is still a draft — never entered the approval chain
    reqs = approval.service.list_requests_for_user(session, users["emp"].id)
    assert all(r.status == "draft" for r in reqs if r.title == "monitors")


def test_agent_submits_draft_in_a_later_turn(session, users):
    """Once the draft exists (created in a prior turn), a fresh turn may submit it —
    this is the confirmed path, so submission must succeed."""
    draft = registry.execute("create_purchase_request",
                             {"title": "monitors", "qty": 3, "unit_price": 200},
                             session=session, user=users["emp"])["result"]
    fake = FakeChat(
        _toolcall("submit_request_for_approval", {"request_no": draft["request_no"]}),
        {"role": "assistant", "content": "Submitted for approval."},
    )
    out = agent.run(session, users["emp"], "yes, submit it", chat=fake)
    submit = out["tool_calls"][0]["result"]["result"]
    # left draft and entered the approval chain (auto-approved here: emp has no approver)
    assert submit["status"] in ("submitted", "approved")
    reqs = approval.service.list_requests_for_user(session, users["emp"].id)
    assert any(r.status != "draft" and r.title == "monitors" for r in reqs)


def test_corrects_chinese_drift_on_korean_input(session, users):
    """Deterministic language backstop: a Korean question that drifts to Chinese is
    regenerated once in Korean (big Qwen drifts ~1 in 5 despite the prompt directives)."""
    fake = FakeChat(
        {"role": "assistant", "content": "抱歉，我不能发送电子邮件给联系人，除非通过工具完成。"},
        {"role": "assistant", "content": "죄송하지만 이메일은 보낼 수 없습니다."},
    )
    out = agent.run(session, users["emp"], "협력사에 이메일 보내줘", chat=fake)
    assert out["reply"] == "죄송하지만 이메일은 보낼 수 없습니다."
    assert fake.i == 2  # one corrective regeneration happened


def test_korean_reply_is_not_regenerated(session, users):
    fake = FakeChat({"role": "assistant", "content": "현재 미지급금은 $3,200입니다."})
    out = agent.run(session, users["emp"], "미지급금 얼마야?", chat=fake)
    assert out["reply"] == "현재 미지급금은 $3,200입니다."
    assert fake.i == 1  # no drift -> no extra call


def test_intentional_chinese_is_left_alone(session, users):
    """If the user themselves wrote Chinese, the reply is not 'corrected'."""
    fake = FakeChat({"role": "assistant", "content": "好的，已经记录下来了。"})
    out = agent.run(session, users["emp"], "请用中文回答：你好吗", chat=fake)
    assert out["reply"] == "好的，已经记录下来了。"
    assert fake.i == 1


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
