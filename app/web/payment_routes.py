"""Payments — instructions the humans execute. Confirming posts to the ledger,
so everything mutating is finance L3."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.payments import service as payments
from .deps import require_login, require_scope, templates

router = APIRouter()
_finance = require_scope("finance", 3)


def _render(request: Request, user, session: Session, error: str | None = None):
    return templates.TemplateResponse(request, "payments.html", {
        "user": user, "instructions": payments.list_instructions(session),
        "today": date.today().isoformat(), "error": error,
    })


@router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request, user=Depends(require_login),
                  session: Session = Depends(get_session)):
    return _render(request, user, session)


@router.post("/payments/prepare", response_class=HTMLResponse)
def payments_prepare(request: Request, bill_no: str = Form(...),
                     user=Depends(_finance),
                     session: Session = Depends(get_session)):
    try:
        payments.prepare_instruction(session, bill_no=bill_no, user=user)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/payments", status_code=303)


@router.post("/payments/{instruction_id}/confirm", response_class=HTMLResponse)
def payments_confirm(request: Request, instruction_id: int,
                     paid_date: str = Form(...), payment_ref: str = Form(""),
                     user=Depends(_finance),
                     session: Session = Depends(get_session)):
    try:
        payments.confirm_executed(session, instruction_id, user=user,
                                  paid_date=date.fromisoformat(paid_date),
                                  payment_ref=payment_ref or None)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/payments", status_code=303)


@router.post("/payments/{instruction_id}/cancel", response_class=HTMLResponse)
def payments_cancel(request: Request, instruction_id: int, user=Depends(_finance),
                    session: Session = Depends(get_session)):
    try:
        payments.cancel_instruction(session, instruction_id, user=user)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/payments", status_code=303)
