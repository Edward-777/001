"""End-to-end 💰 revenue role: customer-invoice task -> draft -> approve -> posted
(docs/AGENT-FLEET.md §2). The AR invoice (revenue recognition) waits for approval."""
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
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import loop, roles
from app.modules.fleet.models import Role, TaskSource, TaskStatus
from app.modules.sales import service as sls


@pytest.fixture
def session():
    from app.wiring import register_all_handlers
    register_all_handlers(force=True)  # so ARInvoicePosted -> revenue journal
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        yield s


def _invoice_task(session, **parsed):
    p = {"customer_name": "ACME Corp",
         "lines": [{"description": "Consulting", "qty": 1, "unit_price": 5000}]}
    p.update(parsed)
    return disp.dispatch(session, category="customer_invoice", title="Bill ACME $5000",
                         source=TaskSource.CEO_CHAT, payload={"parsed": p})


def test_revenue_task_routes_and_drafts(session):
    task = _invoice_task(session)
    assert task.to_role == Role.REVENUE
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL
    assert task.result["amount"] == "5000"
    assert task.result["new_customer"] is True
    # nothing posted yet
    assert sls.list_open_invoices(session) == []


def test_approve_posts_invoice_and_recognizes_revenue(session):
    task = _invoice_task(session)
    loop.run_once(session)
    roles.resolve(session, task, approved=True)
    session.refresh(task)
    assert task.status == TaskStatus.DONE
    assert task.result["invoice_no"]
    # AR invoice now open; revenue recognized (4000 Sales Income credited)
    assert len(sls.list_open_invoices(session)) == 1
    tb = acct.trial_balance(session, as_of=date.today())
    by_code = {r["code"]: r for r in tb["rows"]}
    assert str(by_code["1200"]["debit"]) == "5000.00"   # AR
    assert str(by_code["4000"]["credit"]) == "5000.00"  # Revenue


def test_reject_posts_nothing(session):
    task = _invoice_task(session)
    loop.run_once(session)
    roles.resolve(session, task, approved=False)
    session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert sls.list_open_invoices(session) == []


def test_amount_only_payload_works(session):
    task = _invoice_task(session, lines=None, amount=2500, description="Retainer")
    loop.run_once(session)
    session.refresh(task)
    assert task.result["amount"] == "2500"


def test_missing_customer_fails(session):
    task = _invoice_task(session, customer_name="")
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.FAILED
