"""End-to-end 💸 spend role: invoice task -> draft bill -> approve -> posted
(docs/AGENT-FLEET.md §9). The loop only ever drafts; posting waits for approval."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import loop, roles
from app.modules.fleet.models import Role, TaskSource, TaskStatus
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


def _invoice_task(session, **parsed):
    p = {"vendor_name": "ACME Cloud Inc", "invoice_no": "INV-1", "total": 1200.00}
    p.update(parsed)
    return disp.dispatch(
        session, category="invoice", title="ACME bill", source=TaskSource.UPLOAD,
        payload={"goods_received": True, "parsed": p}, source_ref="doc:1",
    )


def test_loop_drafts_bill_and_parks_for_approval(session):
    task = _invoice_task(session)
    assert task.to_role == Role.SPEND

    n = loop.run_once(session)
    assert n == 1
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL
    # a DRAFT bill exists but is NOT posted yet
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.status == "draft"
    assert str(bill.amount) == "1200.00"
    assert task.result["suggested_account_code"] == "6300"
    # vendor was auto-created (master data) and flagged
    assert task.result["new_vendor"] is True
    assert proc.find_vendor_by_name(session, "ACME Cloud Inc") is not None


def test_approve_posts_the_bill(session):
    task = _invoice_task(session)
    loop.run_once(session)
    roles.resolve(session, task, approved=True)

    session.refresh(task)
    assert task.status == TaskStatus.DONE
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.status == "open"  # posted
    # AP (2000) now carries the credit; expense (6300) the debit
    tb = acct.trial_balance(session, as_of=date.today())
    by_code = {r["code"]: r for r in tb["rows"]}
    assert str(by_code["2000"]["credit"]) == "1200.00"
    assert str(by_code["6300"]["debit"]) == "1200.00"


def test_reject_leaves_bill_unposted(session):
    task = _invoice_task(session)
    loop.run_once(session)
    roles.resolve(session, task, approved=False)

    session.refresh(task)
    assert task.status == TaskStatus.FAILED
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.status == "draft"  # never posted


def test_existing_vendor_is_reused(session):
    proc.create_vendor(session, name="ACME Cloud Inc")
    task = _invoice_task(session)
    loop.run_once(session)
    assert task.result["new_vendor"] is False
    assert len(proc.list_vendors(session)) == 1


def test_invoice_missing_amount_fails_gracefully(session):
    task = _invoice_task(session, total=None)
    n = loop.run_once(session)
    assert n == 1
    session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "missing" in task.bounce_reason


def test_loop_is_idempotent_on_processed_tasks(session):
    _invoice_task(session)
    assert loop.run_once(session) == 1
    # nothing left queued -> a second tick does nothing (no double-draft)
    assert loop.run_once(session) == 0
