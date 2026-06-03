"""expense.service — expense claims (over the approval workflow) + reimbursement.

create_expense_claim creates a generic `requests` row (so it routes through the
org-chart approval), plus the expense-specific extension. On approval, the
handler books Dr expense / Cr Employee Payable; reimburse() pays the employee.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.events import bus
from ...core.sequences import next_number
from ..approval import service as approval
from ..approval.models import RequestType
from .events import ReimbursementPosted
from .models import (
    ExpenseCategory,
    ExpenseClaim,
    ExpenseLine,
    ExpenseStatus,
    ExpenseType,
    Reimbursement,
)

_CENTS = Decimal("0.01")


def create_expense_claim(
    session: Session,
    *,
    requester_user_id: int,
    employee_id: int,
    title: str,
    lines: list[dict],
    expense_type: ExpenseType = ExpenseType.REIMBURSEMENT,
    description: str | None = None,
) -> ExpenseClaim:
    """lines: [{expense_date, category_id, description, amount}].
    Creates a draft request + claim; caller submits via approval.submit_request."""
    total = sum((Decimal(str(ln.get("amount", 0))) for ln in lines), Decimal("0")).quantize(_CENTS)

    req = approval.create_request(
        session,
        type=RequestType.EXPENSE,
        requester_id=requester_user_id,
        title=title,
        description=description,
        lines=[{"description": title, "qty": 1, "unit_price": total}],
    )
    claim = ExpenseClaim(
        request_id=req.id,
        employee_id=employee_id,
        expense_type=str(expense_type),
        total_amount=total,
        status=str(ExpenseStatus.DRAFT),
    )
    session.add(claim)
    session.flush()
    for ln in lines:
        session.add(
            ExpenseLine(
                expense_claim_id=claim.id,
                expense_date=ln.get("expense_date"),
                category_id=ln.get("category_id"),
                description=ln.get("description"),
                amount=Decimal(str(ln.get("amount", 0))).quantize(_CENTS),
                attachment_path=ln.get("attachment_path"),
            )
        )
    session.flush()
    return claim


def get_claim(session: Session, claim_id: int) -> ExpenseClaim | None:
    return session.get(ExpenseClaim, claim_id)


def get_claim_by_request(session: Session, request_id: int) -> ExpenseClaim | None:
    return session.scalar(select(ExpenseClaim).where(ExpenseClaim.request_id == request_id))


def expense_account_lines(session: Session, claim: ExpenseClaim) -> list[dict]:
    """Resolve each expense line's category -> expense account (None if unset;
    accounting falls back). Used by the approval handler."""
    out = []
    for el in claim.lines:
        acct_id = None
        if el.category_id is not None:
            cat = session.get(ExpenseCategory, el.category_id)
            acct_id = cat.default_expense_account_id if cat else None
        out.append({"expense_account_id": acct_id, "amount": Decimal(str(el.amount))})
    return out


def reimburse(
    session: Session,
    claim_id: int,
    *,
    payment_date: date | None = None,
    method: str | None = None,
    bank_account_id: int | None = None,
) -> Reimbursement:
    """Pay the employee for an approved claim. Dr Employee Payable / Cr Cash."""
    claim = session.get(ExpenseClaim, claim_id)
    if claim is None or claim.status != ExpenseStatus.APPROVED:
        raise ValueError("claim not approved")
    pdate = payment_date or date.today()
    reimb = Reimbursement(
        reimbursement_no=next_number(session, "RBM", datetime.now(timezone.utc).year),
        employee_id=claim.employee_id,
        expense_claim_id=claim.id,
        payment_date=pdate,
        amount=Decimal(str(claim.total_amount)),
        method=method,
        bank_account_id=bank_account_id,
    )
    session.add(reimb)
    claim.status = str(ExpenseStatus.REIMBURSED)
    session.flush()
    bus.emit(
        ReimbursementPosted(reimbursement_id=reimb.id, entry_date=pdate,
                            amount=Decimal(str(claim.total_amount))),
        session,
    )
    return reimb
