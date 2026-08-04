"""Autonomy policy engine: fail-closed evaluation, human-only activation, the
breaker, and the L3 spend consumer (auto-post inside an approved envelope,
review card in the same inbox, everything else parks exactly as before)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave, mail,
    notifications, policy, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role as URole
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import loop, roles
from app.modules.fleet.models import Task, TaskSource, TaskStatus
from app.modules.policy import service as svc
from app.modules.policy.models import BREAKER_THRESHOLD, PolicyStatus
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


@pytest.fixture
def admin(session):
    return auth_svc.create_user(session, name="Adm", email="a@x", password="pw",
                                role=URole.ADMIN)


def _active_policy(session, admin, **conditions):
    conditions = conditions or {"max_amount": 200}
    p = svc.propose_policy(session, name="micro spend",
                           action_scope="spend.approve_bill",
                           conditions=conditions, proposed_by=admin.id)
    return svc.activate_policy(session, p.id, user=admin)


# ---- lifecycle ---------------------------------------------------------------

def test_propose_validates_and_fails_closed(session, admin):
    with pytest.raises(ValueError, match="unknown condition keys"):
        svc.propose_policy(session, name="x", action_scope="spend.approve_bill",
                           conditions={"trust_me": True})
    with pytest.raises(ValueError, match="unbounded"):
        svc.propose_policy(session, name="x", action_scope="spend.approve_bill",
                           conditions={})
    with pytest.raises(ValueError, match="unknown action_scope"):
        svc.propose_policy(session, name="x", action_scope="world.domination",
                           conditions={"max_amount": 1})


def test_draft_grants_nothing_until_human_activates(session, admin):
    svc.propose_policy(session, name="micro", action_scope="spend.approve_bill",
                       conditions={"max_amount": 200})
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=50)
    assert d.passed is False and d.resolved_level == 2


def test_no_policy_means_l2_todays_behavior(session):
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=10)
    assert d.passed is False and d.resolved_level == 2 and d.policy_id is None


# ---- conditions ---------------------------------------------------------------

def test_max_amount_boundary(session, admin):
    _active_policy(session, admin, max_amount=200)
    at_cap = svc.evaluate(session, action_scope="spend.approve_bill", amount=200)
    assert at_cap.passed is True and at_cap.resolved_level == 3
    over = svc.evaluate(session, action_scope="spend.approve_bill", amount=200.01)
    assert over.passed is False and over.resolved_level == 2


def test_daily_cap_velocity(session, admin):
    _active_policy(session, admin, max_amount=200, daily_cap=300)
    first = svc.evaluate(session, action_scope="spend.approve_bill", amount=180)
    assert first.passed is True
    second = svc.evaluate(session, action_scope="spend.approve_bill", amount=150)
    assert second.passed is False  # 180 + 150 > 300
    third = svc.evaluate(session, action_scope="spend.approve_bill", amount=100)
    assert third.passed is True    # failed attempts don't consume the cap


def test_vendor_allowlist_condition(session, admin):
    v = proc.create_vendor(session, name="Trusted Co")
    _active_policy(session, admin, max_amount=500, vendor_allowlisted=True)
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=100,
                     vendor_id=v.id)
    assert d.passed is False  # not allowlisted
    v.autonomy_tier = "allowlisted"
    session.flush()
    d2 = svc.evaluate(session, action_scope="spend.approve_bill", amount=100,
                      vendor_id=v.id)
    assert d2.passed is True


def test_budget_headroom_condition(session, admin):
    from app.modules.budget import service as budget_svc
    _active_policy(session, admin, max_amount=500, budget_headroom=True)
    # no budget row -> unbudgeted spend can never auto-execute
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=100,
                     account_code="6300")
    assert d.passed is False
    budget_svc.set_budget(session, account_code="6300",
                          year=date.today().year, monthly_amount=1000)
    d2 = svc.evaluate(session, action_scope="spend.approve_bill", amount=100,
                      account_code="6300")
    assert d2.passed is True
    d3 = svc.evaluate(session, action_scope="spend.approve_bill", amount=1200,
                      account_code="6300")
    assert d3.passed is False  # would blow the monthly budget


def test_expired_policy_is_ignored(session, admin):
    p = svc.propose_policy(session, name="old", action_scope="spend.approve_bill",
                           conditions={"max_amount": 500},
                           effective_to=date.today() - timedelta(days=1))
    svc.activate_policy(session, p.id, user=admin)
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=100)
    assert d.passed is False


def test_breaker_suspends_after_rejections(session, admin):
    p = _active_policy(session, admin, max_amount=200)
    for _ in range(BREAKER_THRESHOLD):
        svc.record_review_rejection(session, p.id)
    session.refresh(p)
    assert p.status == str(PolicyStatus.SUSPENDED)
    assert "breaker" in p.suspend_reason
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=50)
    assert d.passed is False  # suspended grants nothing


# ---- the L3 spend consumer -----------------------------------------------------

def _invoice_task(session, total=120.0, vendor="Trusted Co"):
    return disp.dispatch(
        session, category="invoice", title="bill", source=TaskSource.UPLOAD,
        payload={"goods_received": True,
                 "parsed": {"vendor_name": vendor, "invoice_no": "INV-7",
                            "total": total}},
        source_ref=f"doc:{total}",
    )


def _allowlisted_vendor(session):
    v = proc.create_vendor(session, name="Trusted Co", email="ap@trusted.com")
    v.autonomy_tier = "allowlisted"
    session.flush()
    return v


def test_l3_auto_posts_inside_envelope_with_review_card(session, admin):
    _allowlisted_vendor(session)
    _active_policy(session, admin, max_amount=200, vendor_allowlisted=True)
    task = _invoice_task(session, total=120.0)
    loop.run_once(session)
    session.refresh(task)

    assert task.status == TaskStatus.DONE  # no pre-approval needed
    assert task.result["autonomy"]["auto_executed"] is True
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.status == "open"  # actually posted, through the same code path

    review = [t for t in session.query(Task).all() if t.category == "l3_review"]
    assert len(review) == 1 and review[0].status == TaskStatus.NEEDS_APPROVAL
    assert review[0].payload["task_id"] == task.id


def test_over_envelope_parks_exactly_like_before(session, admin):
    _allowlisted_vendor(session)
    _active_policy(session, admin, max_amount=200, vendor_allowlisted=True)
    task = _invoice_task(session, total=350.0)
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL  # L2, today's behavior
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.status == "draft"
    assert task.result["autonomy"]["resolved_level"] == 2


def test_new_vendor_never_auto_posts_even_inside_envelope(session, admin):
    # envelope with no vendor condition — but the vendor is auto-created from
    # the inbound document, so the consumer's extra belt must park it
    _active_policy(session, admin, max_amount=200)
    task = _invoice_task(session, total=100.0, vendor="Never Seen Before LLC")
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL


def test_rejecting_review_card_flags_policy_until_breaker(session, admin):
    _allowlisted_vendor(session)
    p = _active_policy(session, admin, max_amount=200, vendor_allowlisted=True)
    for i in range(BREAKER_THRESHOLD):
        task = _invoice_task(session, total=50.0 + i)
        loop.run_once(session)
        review = [t for t in session.query(Task).all()
                  if t.category == "l3_review"
                  and t.status == TaskStatus.NEEDS_APPROVAL]
        roles.resolve(session, review[-1], approved=False)
    session.refresh(p)
    assert p.status == str(PolicyStatus.SUSPENDED)
    # next bill inside the old envelope parks again — autonomy is revoked
    task = _invoice_task(session, total=60.0)
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL


# ---- AI tools -------------------------------------------------------------------

def test_ai_can_propose_but_never_activate(session, admin):
    from app.modules.ai.registry import registry
    out = registry.execute("propose_autonomy_policy",
                           {"name": "micro", "conditions": {"max_amount": 100}},
                           session=session, user=admin)["result"]
    assert out["status"] == "draft"
    assert "grants nothing" in out["note"].lower() or "grants NOTHING" in out["note"]
    # no activation tool exists in the registry
    names = [t["function"]["name"] for t in registry.schemas_for(admin)]
    assert "activate_autonomy_policy" not in names
    # and the drafted policy indeed grants nothing
    d = svc.evaluate(session, action_scope="spend.approve_bill", amount=10)
    assert d.passed is False
