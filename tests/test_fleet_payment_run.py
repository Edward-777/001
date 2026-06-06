"""Weekly payment run: propose open bills -> approve -> disbursements posted
(docs/AGENT-FLEET.md §4)."""
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
from app.modules.fleet import payment_run, roles
from app.modules.fleet import service as q
from app.modules.fleet.models import Role, TaskStatus
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        yield s


def _open_bill(session, vendor_name, amount):
    """A posted (open) vendor bill with a balance to pay."""
    v = proc.create_vendor(session, name=vendor_name)
    bill = acct.create_ap_bill(
        session, vendor_id=v.id,
        lines=[{"description": "svc", "qty": 1, "unit_price": amount}])
    exp = acct.get_account_by_code(session, "6300")
    acct.post_direct_bill(session, bill.id, exp.id)  # -> status open
    return bill


def test_payment_run_lists_open_bills(session):
    _open_bill(session, "ACME", 1000)
    _open_bill(session, "Globex", 2500)
    task = payment_run.enqueue_weekly_payment_run(session, as_of=date(2026, 6, 1))
    assert task.status == TaskStatus.NEEDS_APPROVAL
    assert task.to_role == Role.ACCOUNTING
    assert task.result["count"] == 2
    assert task.result["total"] == "3500.00"


def test_no_open_bills_no_task(session):
    assert payment_run.enqueue_weekly_payment_run(session, as_of=date(2026, 6, 1)) is None


def test_idempotent_per_week(session):
    _open_bill(session, "ACME", 1000)
    a = payment_run.enqueue_weekly_payment_run(session, as_of=date(2026, 6, 1))
    b = payment_run.enqueue_weekly_payment_run(session, as_of=date(2026, 6, 3))  # same ISO week
    assert a.id == b.id
    assert len(q.list_tasks(session)) == 1


def test_approve_records_payments(session):
    bill = _open_bill(session, "ACME", 1000)
    task = payment_run.enqueue_weekly_payment_run(session, as_of=date(2026, 6, 1))
    roles.resolve(session, task, approved=True)
    session.refresh(task)
    assert task.status == TaskStatus.DONE
    # the bill is now paid (balance cleared)
    paid_bill = acct.get_ap_bill(session, bill.id)
    assert str(paid_bill.balance) == "0.00"
    assert paid_bill.status == "paid"
    assert task.result["paid"] == [bill.bill_no]
