"""Contracts register: validation, the notice-window math, the weekly founder
alert, and the AI tools."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register tables
    accounting, ai, approval, auth, contracts, documents, fleet, hr, procurement,
)
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Scope
from app.modules.contracts import service as svc
from app.modules.contracts.models import ContractStatus
from app.modules.fleet import alerts
from app.modules.fleet.models import Role, TaskStatus

TODAY = date(2026, 7, 28)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _lease(session, **kw):
    defaults = dict(title="Office lease", counterparty="Acme Properties",
                    kind="lease", end_date=date(2026, 9, 30), notice_days=60,
                    amount=3000, billing="monthly")
    defaults.update(kw)
    return svc.add_contract(session, **defaults)


def test_add_validates_inputs(session):
    with pytest.raises(ValueError, match="title and counterparty"):
        svc.add_contract(session, title=" ", counterparty="X")
    with pytest.raises(ValueError, match="kind"):
        svc.add_contract(session, title="T", counterparty="X", kind="nda")
    with pytest.raises(ValueError, match="before start_date"):
        svc.add_contract(session, title="T", counterparty="X",
                         start_date=date(2026, 5, 1), end_date=date(2026, 4, 1))
    with pytest.raises(ValueError, match="billing"):
        svc.add_contract(session, title="T", counterparty="X", billing="weekly")


def test_notice_window_math(session):
    c = _lease(session)  # ends 09-30, notice 60d -> window opens 08-01
    assert svc.upcoming_renewals(session, as_of=date(2026, 7, 31)) == []
    due = svc.upcoming_renewals(session, as_of=date(2026, 8, 1))
    assert [r["contract_id"] for r in due] == [c.id]
    assert due[0]["days_left"] == 60
    assert "expires" in due[0]["action"]
    # past the end date the row stays (overdue), with a different action hint
    over = svc.upcoming_renewals(session, as_of=date(2026, 10, 2))
    assert over[0]["days_left"] == -2 and "expired" in over[0]["action"]


def test_auto_renew_gets_cancel_hint(session):
    _lease(session, auto_renew=True, title="SaaS sub", kind="subscription")
    due = svc.upcoming_renewals(session, as_of=date(2026, 9, 1))
    assert "cancel before" in due[0]["action"]


def test_ended_contracts_leave_the_radar(session):
    c = _lease(session)
    svc.end_contract(session, c.id)
    assert c.status == str(ContractStatus.ENDED)
    assert svc.upcoming_renewals(session, as_of=date(2026, 9, 1)) == []
    with pytest.raises(ValueError, match="already"):
        svc.end_contract(session, c.id)


def test_renewal_alert_parked_weekly_and_idempotent(session):
    _lease(session)
    t1 = alerts.enqueue_renewal_alerts(session, as_of=date(2026, 8, 3))
    assert t1.to_role == Role.INSIGHT
    assert t1.status == TaskStatus.NEEDS_APPROVAL
    assert t1.result["count"] == 1
    # same week -> same task; nothing new is parked
    t2 = alerts.enqueue_renewal_alerts(session, as_of=date(2026, 8, 4))
    assert t1.id == t2.id
    # a NEW due contract changes the key -> a fresh alert fires the same week
    _lease(session, title="E&O insurance", kind="insurance",
           end_date=date(2026, 8, 20), notice_days=30)
    t3 = alerts.enqueue_renewal_alerts(session, as_of=date(2026, 8, 4))
    assert t3.id != t1.id and t3.result["count"] == 2


def test_no_alert_when_nothing_due(session):
    _lease(session)
    assert alerts.enqueue_renewal_alerts(session, as_of=date(2026, 7, 1)) is None


# ---- AI tools ---------------------------------------------------------------

@pytest.fixture
def finance_user(session):
    u = auth_svc.create_user(session, name="Fin", email="f@x", password="pw")
    auth_svc.grant_scope(session, u, Scope.FINANCE, 2, DataBoundary.ALL)
    return u


def test_ai_tools_roundtrip(session, finance_user):
    from app.modules.ai.registry import registry
    out = registry.execute("add_contract", {
        "title": "Slack", "counterparty": "Salesforce", "kind": "subscription",
        "end_date": "2026-08-15", "auto_renew": True, "notice_days": 30,
        "amount": 96.0, "billing": "monthly"},
        session=session, user=finance_user)["result"]
    assert out["contract_id"] and out["auto_renew"] is True

    lst = registry.execute("list_contracts", {}, session=session,
                           user=finance_user)["result"]
    assert lst["count"] == 1

    due = registry.execute("upcoming_renewals", {}, session=session,
                           user=finance_user)["result"]
    assert due["count"] == 1  # 08-15 is inside 30d of 2026-07-28 (today)

    ended = registry.execute("end_contract", {"contract_id": out["contract_id"]},
                             session=session, user=finance_user)["result"]
    assert ended["status"] == "ended"


def test_ai_tools_need_finance_scope(session):
    from app.modules.ai.registry import registry
    plain = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")
    out = registry.execute("list_contracts", {}, session=session, user=plain)
    assert "permission denied" in out.get("error", "")
