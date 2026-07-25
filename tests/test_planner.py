"""Planner/Executor stage 1: template plans, gated LLM planning, sequential
step execution, failure honesty, and the maker-checker gate spanning ALL steps."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, hr  # noqa: F401  register
from app.modules.ai import agent, planner
from app.modules.auth import service as auth_svc


# ---- planner unit ---------------------------------------------------------

def test_month_close_gets_template_plan_without_llm():
    def boom(*a, **k):
        raise AssertionError("LLM called for a template intent")
    steps = planner.maybe_plan("Close June for me", chat=boom)
    assert steps == planner._CLOSE_PLAN
    assert planner.maybe_plan("6월 마감 진행해줘", chat=boom) == planner._CLOSE_PLAN


def test_simple_question_skips_planning_entirely():
    def boom(*a, **k):
        raise AssertionError("LLM planning call for a simple question")
    assert planner.maybe_plan("How much runway do we have?", chat=boom) is None


def test_multi_action_message_planned_via_llm():
    fake = lambda msgs, **k: {"content": '{"steps": ["Register the vendor", "Issue the PO"]}'}
    steps = planner.maybe_plan(
        "Register Acme as a vendor and then issue the pending PO to them", chat=fake)
    assert steps == ["Register the vendor", "Issue the PO"]


def test_llm_garbage_or_empty_degrades_to_no_plan():
    fake = lambda msgs, **k: {"content": "sure, here is some prose"}
    assert planner.maybe_plan("Do this and then do that please, thanks a lot",
                              chat=fake) is None
    fake2 = lambda msgs, **k: {"content": '{"steps": []}'}
    assert planner.maybe_plan("Do this and then do that please, thanks a lot",
                              chat=fake2) is None


# ---- executor integration -------------------------------------------------

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
    """Returns queued responses in order; records every call's messages."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def test_plan_executes_steps_and_composes(session, user):
    chat = ScriptedChat([
        # planner call (message carries ' and ')
        {"content": '{"steps": ["Look up the stock", "Summarize the position"]}'},
        # step 1 loop -> direct answer
        {"content": "Stock is 90 units."},
        # step 2 loop -> direct answer
        {"content": "Position is healthy."},
        # final compose
        {"content": "Stock is 90 units and the position is healthy."},
    ])
    out = agent.run(session, user,
                    "Check the widget stock and then summarize our inventory position",
                    chat=chat)
    assert out["plan"] == [
        {"title": "Look up the stock", "status": "done"},
        {"title": "Summarize the position", "status": "done"},
    ]
    assert "healthy" in out["reply"]
    # step 2's directive carried step 1's result forward
    step2_sys = " ".join(m.get("content", "") for m in chat.calls[2]["messages"]
                         if m.get("role") == "system")
    assert "Stock is 90 units." in step2_sys
    # compose ran WITHOUT tools
    assert chat.calls[-1]["tools"] is None


def test_failed_step_skips_rest_and_reply_admits_it(session, user):
    exhaust = {"content": "", "tool_calls": [
        {"function": {"name": "nonexistent_tool", "arguments": {}}}]}
    chat = ScriptedChat([
        {"content": '{"steps": ["Step A", "Step B", "Step C"]}'},
        # step A: every iteration calls a failing tool -> loop exhausts (6 iters)
        *[exhaust] * 6,
        # final compose
        {"content": "Step A could not be completed."},
    ])
    out = agent.run(session, user, "Do A and then B and then C for the report",
                    chat=chat)
    statuses = [s["status"] for s in out["plan"]]
    assert statuses == ["failed", "skipped", "skipped"]
    assert "could not" in out["reply"]


def test_maker_checker_spans_plan_steps(session, user):
    """A plan may NOT create a money draft in one step and submit it in another —
    the human-confirmation gate covers the whole user turn."""
    chat = ScriptedChat([
        {"content": '{"steps": ["Create the purchase request", "Submit it"]}'},
        # step 1: create a draft (valid args)
        {"content": "", "tool_calls": [{"function": {
            "name": "create_purchase_request",
            "arguments": {"title": "Desks", "qty": 2, "unit_price": 100}}}]},
        {"content": "Draft created."},
        # step 2: try to submit in the SAME user turn
        {"content": "", "tool_calls": [{"function": {
            "name": "submit_request_for_approval",
            "arguments": {"request_no": "REQ-XXXX"}}}]},
        {"content": "Submission was blocked pending confirmation."},
        # final compose
        {"content": "Draft created; submission awaits your confirmation."},
    ])
    out = agent.run(session, user,
                    "Create a purchase request for 2 desks at $100 and submit it",
                    chat=chat)
    submit_calls = [c for c in out["tool_calls"]
                    if c["tool"] == "submit_request_for_approval"]
    assert submit_calls and submit_calls[0]["ok"] is False
    assert "confirmation required" in str(submit_calls[0]["result"])
