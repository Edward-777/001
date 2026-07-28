"""Budget vs actual: actuals derived from the posted ledger, expense-only
budgets, unbudgeted-spend honesty, the overrun alert, and the AI tools."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, ai, approval, auth, budget, documents, fleet, hr,
    notifications, procurement,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Scope
from app.modules.budget import service as svc
from app.modules.fleet import alerts
from app.modules.fleet.models import Role, TaskStatus

JULY = date(2026, 7, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


def _spend(session, d, amount, code="6100"):
    dr = acct.get_account_by_code(session, code)
    cr = acct.get_account_by_code(session, "1000")
    acct.post_journal(session, entry_date=d,
                      lines=[acct.Line(dr.id, debit=amount), acct.Line(cr.id, credit=amount)],
                      description="spend")


def test_budget_only_on_expense_accounts(session):
    with pytest.raises(ValueError, match="not an expense account"):
        svc.set_budget(session, account_code="1000", year=2026, monthly_amount=100)
    with pytest.raises(ValueError, match="unknown account"):
        svc.set_budget(session, account_code="9999", year=2026, monthly_amount=100)


def test_actual_comes_from_posted_ledger(session):
    svc.set_budget(session, account_code="6100", year=2026, monthly_amount=1000)
    _spend(session, date(2026, 7, 5), 400)
    _spend(session, date(2026, 7, 20), 250)
    _spend(session, date(2026, 6, 10), 999)   # other month — not this month's actual
    r = svc.budget_vs_actual(session, year=2026, month=7)
    row = r["rows"][0]
    assert row["account_code"] == "6100"
    assert row["month_actual"] == "650.00"
    assert row["month_remaining"] == "350.00"
    assert row["month_pct"] == 65.0
    assert row["over"] is False
    # YTD: budget 1000*7, actual = 999 + 650
    assert row["ytd_budget"] == "7000.00" and row["ytd_actual"] == "1649.00"


def test_unbudgeted_spend_is_reported_not_hidden(session):
    svc.set_budget(session, account_code="6100", year=2026, monthly_amount=1000)
    _spend(session, date(2026, 7, 5), 123, code="6300")  # office supplies, no budget
    r = svc.budget_vs_actual(session, year=2026, month=7)
    assert [(u["account_code"], u["month_actual"]) for u in r["unbudgeted"]] \
        == [("6300", "123.00")]


def test_overrun_alert_parked_and_idempotent(session):
    svc.set_budget(session, account_code="6100", year=2026, monthly_amount=1000)
    _spend(session, JULY, 1500)
    t1 = alerts.enqueue_budget_alerts(session, as_of=JULY)
    assert t1.to_role == Role.INSIGHT and t1.status == TaskStatus.NEEDS_APPROVAL
    assert t1.result["overruns"][0]["account_code"] == "6100"
    t2 = alerts.enqueue_budget_alerts(session, as_of=date(2026, 7, 20))
    assert t1.id == t2.id  # same month, same over-set -> same card
    # a second account going over re-alerts within the month
    svc.set_budget(session, account_code="6300", year=2026, monthly_amount=100)
    _spend(session, date(2026, 7, 21), 200, code="6300")
    t3 = alerts.enqueue_budget_alerts(session, as_of=date(2026, 7, 22))
    assert t3.id != t1.id and t3.result["count"] == 2


def test_no_alert_under_budget(session):
    svc.set_budget(session, account_code="6100", year=2026, monthly_amount=1000)
    _spend(session, JULY, 900)
    assert alerts.enqueue_budget_alerts(session, as_of=JULY) is None


def test_consumption_note(session):
    svc.set_budget(session, account_code="6100", year=2026, monthly_amount=1000)
    _spend(session, JULY, 900)
    a = acct.get_account_by_code(session, "6100")
    note = svc.consumption_note(session, account_id=a.id, add_amount=0, on_date=JULY)
    assert "900.00 of $1000.00" in note and "OVER" not in note
    _spend(session, JULY, 200)
    note = svc.consumption_note(session, account_id=a.id, add_amount=0, on_date=JULY)
    assert "OVER BUDGET" in note
    # unbudgeted account -> nothing to say
    b = acct.get_account_by_code(session, "6300")
    assert svc.consumption_note(session, account_id=b.id, add_amount=0,
                                on_date=JULY) is None


# ---- AI tools ---------------------------------------------------------------

@pytest.fixture
def cfo(session):
    u = auth_svc.create_user(session, name="CFO", email="c@x", password="pw")
    auth_svc.grant_scope(session, u, Scope.FINANCE, 3, DataBoundary.ALL)
    return u


def test_ai_tools_set_and_report(session, cfo):
    from app.modules.ai.registry import registry
    out = registry.execute("set_budget",
                           {"account_code": "6100", "year": 2026,
                            "monthly_amount": 1000},
                           session=session, user=cfo)["result"]
    assert out["monthly_amount"] == "1000.00"
    _spend(session, date(2026, 7, 5), 400)
    r = registry.execute("budget_vs_actual", {"year": 2026, "month": 7},
                         session=session, user=cfo)["result"]
    assert r["rows"][0]["month_actual"] == "400.00"

    # never guess a budget figure
    bad = registry.execute("set_budget", {"account_code": "6100"},
                           session=session, user=cfo)["result"]
    assert "error" in bad


def test_budget_tools_need_finance_l3(session):
    from app.modules.ai.registry import registry
    plain = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")
    out = registry.execute("budget_vs_actual", {}, session=session, user=plain)
    assert "permission denied" in out.get("error", "")
