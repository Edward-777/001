"""M11 — expense / reimbursement, the flagship travel scenario:
create claim -> org-chart approval -> Dr Travel Expense / Cr Employee Payable
-> reimburse -> Dr Employee Payable / Cr Cash."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.accounting.handlers import register_handlers as register_accounting
from app.modules.accounting.ledger_models import JournalEntry, JournalLine
from app.modules.approval import service as appr
from app.modules.auth import service as auth_svc
from app.modules.expense import service as exp
from app.modules.expense.handlers import register_handlers as register_expense
from app.modules.expense.models import ExpenseCategory, ExpenseStatus
from app.modules.hr import service as hr_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        appr.seed_approval_rules(s)
        register_expense()      # approved expense -> ExpenseApproved
        register_accounting()   # ExpenseApproved/Reimbursement -> JE
        s.flush()
        yield s


@pytest.fixture
def org(session):
    people = {}
    parent = None
    for name in ["mgr", "staff"]:
        u = auth_svc.create_user(session, name=name, email=f"{name}@001.local", password="pw")
        session.flush()
        e = hr_svc.create_employee(session, employee_no=name.upper(), name=name,
                                   reports_to_id=parent.id if parent else None, user_id=u.id)
        people[name] = dict(user=u, emp=e)
        parent = e
    session.flush()
    return people


def _role(session, role):
    return acct.get_account_by_role(session, role).id


def _je(session, source_type, *, contains=None):
    jes = [j for j in session.scalars(select(JournalEntry)) if j.source_type == source_type]
    if contains:
        jes = [j for j in jes if contains in (j.description or "")]
    je = jes[-1]
    rows = session.scalars(select(JournalLine).where(JournalLine.je_id == je.id)).all()
    return {ln.account_id: (ln.debit, ln.credit) for ln in rows}


def _emp_payable(session):
    acc = _role(session, "employee_payable")
    rows = session.scalars(select(JournalLine).where(JournalLine.account_id == acc)).all()
    return sum((Decimal(str(r.credit)) - Decimal(str(r.debit)) for r in rows), Decimal("0"))


def test_travel_claim_full_flow(session, org):
    travel = ExpenseCategory(name="Travel", default_expense_account_id=_role(session, "travel_expense"))
    session.add(travel)
    session.flush()

    # "5/1~15 Korea conference trip" -> $500
    claim = exp.create_expense_claim(
        session, requester_user_id=org["staff"]["user"].id, employee_id=org["staff"]["emp"].id,
        title="Korea conference trip 5/1-15",
        lines=[{"category_id": travel.id, "amount": 500, "description": "flight+hotel"}],
    )
    assert claim.total_amount == 500

    appr.submit_request(session, claim.request_id)   # expense 0-1000 -> mgr
    appr.approve(session, claim.request_id, org["mgr"]["user"].id)

    # claim approved + booked Dr Travel 500 / Cr Employee Payable 500
    assert claim.status == ExpenseStatus.APPROVED
    by = _je(session, "expense", contains="claim")
    assert by[_role(session, "travel_expense")] == (Decimal("500.00"), Decimal("0.00"))
    assert by[_role(session, "employee_payable")] == (Decimal("0.00"), Decimal("500.00"))
    assert _emp_payable(session) == Decimal("500.00")

    # reimburse the employee -> Dr Employee Payable / Cr Cash
    exp.reimburse(session, claim.id)
    assert claim.status == ExpenseStatus.REIMBURSED
    by = _je(session, "expense", contains="Reimbursement")
    assert by[_role(session, "employee_payable")] == (Decimal("500.00"), Decimal("0.00"))
    assert by[_role(session, "cash")] == (Decimal("0.00"), Decimal("500.00"))
    assert _emp_payable(session) == Decimal("0.00")  # liability cleared


def test_uncategorized_expense_falls_back_to_supplies(session, org):
    claim = exp.create_expense_claim(
        session, requester_user_id=org["staff"]["user"].id, employee_id=org["staff"]["emp"].id,
        title="Misc", lines=[{"amount": 80, "description": "stuff"}],  # no category
    )
    appr.submit_request(session, claim.request_id)
    appr.approve(session, claim.request_id, org["mgr"]["user"].id)
    by = _je(session, "expense", contains="claim")
    assert by[_role(session, "supplies_expense")] == (Decimal("80.00"), Decimal("0.00"))


def test_cannot_reimburse_unapproved_claim(session, org):
    claim = exp.create_expense_claim(
        session, requester_user_id=org["staff"]["user"].id, employee_id=org["staff"]["emp"].id,
        title="x", lines=[{"amount": 50}],
    )
    with pytest.raises(ValueError, match="approved"):
        exp.reimburse(session, claim.id)


def test_multi_category_claim_groups_debits(session, org):
    travel = ExpenseCategory(name="Travel", default_expense_account_id=_role(session, "travel_expense"))
    session.add(travel)
    session.flush()
    claim = exp.create_expense_claim(
        session, requester_user_id=org["staff"]["user"].id, employee_id=org["staff"]["emp"].id,
        title="Trip", lines=[
            {"category_id": travel.id, "amount": 300, "description": "flight"},
            {"category_id": travel.id, "amount": 200, "description": "hotel"},
            {"amount": 50, "description": "misc"},  # supplies fallback
        ],
    )
    appr.submit_request(session, claim.request_id)
    appr.approve(session, claim.request_id, org["mgr"]["user"].id)
    by = _je(session, "expense", contains="claim")
    assert by[_role(session, "travel_expense")] == (Decimal("500.00"), Decimal("0.00"))  # 300+200
    assert by[_role(session, "supplies_expense")] == (Decimal("50.00"), Decimal("0.00"))
    assert by[_role(session, "employee_payable")] == (Decimal("0.00"), Decimal("550.00"))
