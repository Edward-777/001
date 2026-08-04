"""Compliance calendar: validation, self-perpetuating recurrence, the notice
window, the idempotent seed catalog, the weekly inbox card, and the AI tools."""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave, mail,
    notifications, obligations, policy, procurement, sales,
)
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Role as URole, Scope
from app.modules.fleet import alerts
from app.modules.fleet.models import Role, TaskStatus
from app.modules.obligations import service as svc
from app.modules.obligations.models import ObligationStatus

TODAY = date.today()


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_add_validates(session):
    with pytest.raises(ValueError, match="name"):
        svc.add_obligation(session, name=" ", due_date=TODAY)
    with pytest.raises(ValueError, match="category"):
        svc.add_obligation(session, name="x", due_date=TODAY, category="vibes")
    with pytest.raises(ValueError, match="recurrence"):
        svc.add_obligation(session, name="x", due_date=TODAY,
                           recurrence="whenever")


def test_completing_recurring_duty_spawns_next(session):
    o = svc.add_obligation(session, name="Form 941", due_date=date(2026, 10, 31),
                           category="tax", recurrence="quarterly")
    svc.complete_obligation(session, o.id)
    assert o.status == str(ObligationStatus.DONE)
    open_ = svc.list_obligations(session)
    assert len(open_) == 1
    assert open_[0].name == "Form 941"
    assert open_[0].due_date == date(2027, 1, 31)  # +3mo, month-end preserved


def test_advance_preserves_month_end_and_clamps_short_months(session):
    # month-end stays month-end across quarters (941 cadence)
    assert svc._advance(date(2026, 10, 31), "quarterly") == date(2027, 1, 31)
    assert svc._advance(date(2027, 1, 31), "quarterly") == date(2027, 4, 30)
    # Feb clamps but a mid-month day is untouched
    assert svc._advance(date(2026, 11, 30), "quarterly") == date(2027, 2, 28)
    assert svc._advance(date(2028, 11, 30), "quarterly") == date(2029, 2, 28)
    assert svc._advance(date(2026, 1, 15), "monthly") == date(2026, 2, 15)
    # annual leap-day case
    assert svc._advance(date(2028, 2, 29), "annual") == date(2029, 2, 28)


def test_dismiss_spawns_nothing(session):
    o = svc.add_obligation(session, name="DE franchise", due_date=date(2027, 3, 1),
                           recurrence="annual")
    svc.dismiss_obligation(session, o.id, reason="not a DE entity")
    assert svc.list_obligations(session) == []
    assert "dismissed: not a DE entity" in o.notes


def test_upcoming_window_and_overdue(session):
    svc.add_obligation(session, name="soon", due_date=TODAY + timedelta(days=10),
                       notice_days=21)
    svc.add_obligation(session, name="far", due_date=TODAY + timedelta(days=90),
                       notice_days=21)
    svc.add_obligation(session, name="late", due_date=TODAY - timedelta(days=3),
                       notice_days=21)
    due = svc.upcoming(session)
    names = [d["name"] for d in due]
    assert "soon" in names and "late" in names and "far" not in names
    late = next(d for d in due if d["name"] == "late")
    assert late["overdue"] is True and late["days_left"] == -3


def test_seed_is_idempotent_and_future_dated(session):
    first = svc.seed_us_basics(session)
    assert len(first) >= 6
    assert all(o.due_date >= TODAY for o in first)
    again = svc.seed_us_basics(session)
    assert again == []  # nothing duplicated
    names = [o.name for o in svc.list_obligations(session)]
    assert any("941" in n for n in names)
    assert any("B&O" in n for n in names)
    assert any("1099" in n for n in names)


def test_obligation_alert_card_idempotent_per_week(session):
    svc.add_obligation(session, name="WA B&O", due_date=TODAY + timedelta(days=5),
                       notice_days=21)
    t1 = alerts.enqueue_obligation_alerts(session, as_of=TODAY)
    assert t1.to_role == Role.INSIGHT and t1.status == TaskStatus.NEEDS_APPROVAL
    t2 = alerts.enqueue_obligation_alerts(session, as_of=TODAY)
    assert t1.id == t2.id
    # a newly due obligation re-alerts within the same week
    svc.add_obligation(session, name="941", due_date=TODAY + timedelta(days=8),
                       notice_days=21)
    t3 = alerts.enqueue_obligation_alerts(session, as_of=TODAY)
    assert t3.id != t1.id and t3.result["count"] == 2


def test_no_alert_when_calendar_is_quiet(session):
    svc.add_obligation(session, name="far", due_date=TODAY + timedelta(days=200),
                       notice_days=21)
    assert alerts.enqueue_obligation_alerts(session, as_of=TODAY) is None


# ---- AI tools -----------------------------------------------------------------

def test_ai_tools_roundtrip_and_gates(session):
    from app.modules.ai.registry import registry

    plain = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")
    denied = registry.execute("upcoming_deadlines", {}, session=session, user=plain)
    assert "permission denied" in denied.get("error", "")

    cfo = auth_svc.create_user(session, name="CFO", email="c@x", password="pw")
    auth_svc.grant_scope(session, cfo, Scope.FINANCE, 3, DataBoundary.ALL)

    added = registry.execute("add_obligation",
                             {"name": "City license", "due_date": "2027-01-15",
                              "recurrence": "annual"},
                             session=session, user=cfo)["result"]
    assert added["recurrence"] == "annual"

    due = registry.execute("upcoming_deadlines", {"within_days": 400},
                           session=session, user=cfo)["result"]
    assert due["count"] == 1

    done = registry.execute("complete_obligation",
                            {"obligation_id": added["obligation_id"]},
                            session=session, user=cfo)["result"]
    assert done["status"] == "done"
    assert "next occurrence" in done["note"]
