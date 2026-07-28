"""Contracts register page — finance L2 (amounts are visible here)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.contracts import service as contracts
from .deps import require_scope, templates

router = APIRouter()
_finance2 = require_scope("finance", 2)


def _render(request: Request, user, session: Session, error: str | None = None):
    rows = contracts.list_contracts(session, include_ended=True)
    due_ids = {r["contract_id"] for r in contracts.upcoming_renewals(session)}
    return templates.TemplateResponse(request, "contracts.html", {
        "user": user, "contracts": rows, "due_ids": due_ids,
        "days_left": {c.id: contracts.days_left(c) for c in rows},
        "error": error,
    })


@router.get("/contracts", response_class=HTMLResponse)
def contracts_page(request: Request, user=Depends(_finance2),
                   session: Session = Depends(get_session)):
    return _render(request, user, session)


@router.post("/contracts/add", response_class=HTMLResponse)
def contracts_add(request: Request,
                  title: str = Form(...), counterparty: str = Form(...),
                  kind: str = Form("other"), start_date: str = Form(""),
                  end_date: str = Form(""), auto_renew: bool = Form(False),
                  notice_days: int = Form(30), amount: str = Form(""),
                  billing: str = Form(""), notes: str = Form(""),
                  user=Depends(_finance2), session: Session = Depends(get_session)):
    try:
        contracts.add_contract(
            session, title=title, counterparty=counterparty, kind=kind,
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
            auto_renew=auto_renew, notice_days=notice_days,
            amount=float(amount) if amount else None,
            billing=billing or None, notes=notes or None, created_by=user.id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/contracts", status_code=303)


@router.post("/contracts/{contract_id}/end", response_class=HTMLResponse)
def contracts_end(request: Request, contract_id: int, user=Depends(_finance2),
                  session: Session = Depends(get_session)):
    try:
        contracts.end_contract(session, contract_id, ended_by=user.id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/contracts", status_code=303)
