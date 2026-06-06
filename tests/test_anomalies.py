"""Spend anomaly detection + insight alert (docs/AGENT-FLEET.md §2)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.fleet import alerts
from app.modules.fleet.models import Role, TaskStatus
from app.modules.procurement import service as proc

AS_OF = date(2026, 6, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


def _rent(session, d, amount):
    dr = acct.get_account_by_code(session, "6100")  # Rent Expense
    cr = acct.get_account_by_code(session, "1000")  # Checking
    acct.post_journal(session, entry_date=d,
                      lines=[acct.Line(dr.id, debit=amount), acct.Line(cr.id, credit=amount)],
                      description="rent")


def test_spend_spike_detected(session):
    for m in (3, 4, 5):                       # baseline $1000/mo
        _rent(session, date(2026, m, 10), 1000)
    _rent(session, date(2026, 6, 10), 5000)   # spike this month
    found = acct.spend_anomalies(session, as_of=AS_OF, trailing_months=3)
    spikes = [a for a in found if a["account_code"] == "6100"]
    assert len(spikes) == 1
    assert spikes[0]["current"] == "5000.00"
    assert spikes[0]["baseline"] == "1000.00"
    assert spikes[0]["factor"] == "5.0"


def test_steady_spend_not_flagged(session):
    for m in (3, 4, 5, 6):
        _rent(session, date(2026, m, 10), 1000)
    assert acct.spend_anomalies(session, as_of=AS_OF, trailing_months=3) == []


def test_duplicate_bills_detected(session):
    v = proc.create_vendor(session, name="ACME")
    for d in (date(2026, 6, 1), date(2026, 6, 3)):
        acct.create_ap_bill(session, vendor_id=v.id, bill_date=d,
                             lines=[{"description": "svc", "qty": 1, "unit_price": 800}])
    dups = acct.duplicate_bills(session, window_days=7)
    assert len(dups) == 1
    assert dups[0]["amount"] == "800.00"
    assert len(dups[0]["bill_nos"]) == 2


def test_distant_same_amount_not_duplicate(session):
    v = proc.create_vendor(session, name="ACME")
    for d in (date(2026, 1, 1), date(2026, 6, 1)):  # far apart -> recurring, not dup
        acct.create_ap_bill(session, vendor_id=v.id, bill_date=d,
                             lines=[{"description": "svc", "qty": 1, "unit_price": 800}])
    assert acct.duplicate_bills(session, window_days=7) == []


def test_alert_parked_when_anomalies_and_idempotent(session):
    for m in (3, 4, 5):
        _rent(session, date(2026, m, 10), 1000)
    _rent(session, date(2026, 6, 10), 5000)
    t1 = alerts.enqueue_anomaly_alerts(session, as_of=AS_OF)
    assert t1.to_role == Role.INSIGHT
    assert t1.status == TaskStatus.NEEDS_APPROVAL
    assert t1.result["count"] >= 1
    t2 = alerts.enqueue_anomaly_alerts(session, as_of=AS_OF)  # same day -> same task
    assert t1.id == t2.id


def test_no_alert_when_clean(session):
    assert alerts.enqueue_anomaly_alerts(session, as_of=AS_OF) is None
