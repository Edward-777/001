"""expense reacts to approval: when an expense request is approved, mark the
claim approved and emit ExpenseApproved (accounting books it)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ...core.events import bus
from ..approval.events import RequestApproved
from . import service
from .events import ExpenseApproved
from .models import ExpenseStatus


def on_request_approved(event: RequestApproved, session: Session) -> None:
    if event.request_type not in ("expense", "trip"):
        return
    claim = service.get_claim_by_request(session, event.request_id)
    if claim is None:
        return
    claim.status = str(ExpenseStatus.APPROVED)
    session.flush()
    bus.emit(
        ExpenseApproved(
            claim_id=claim.id,
            entry_date=date.today(),
            lines=service.expense_account_lines(session, claim),
        ),
        session,
    )


def register_handlers() -> None:
    bus.subscribe(RequestApproved, on_request_approved)
