"""Compliance calendar — the company's time axis. Completing/dismissing a duty
is a compliance assertion, so mutations sit at finance L3."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.obligations import service as obligations
from .deps import require_login, require_scope, templates

router = APIRouter()
_finance = require_scope("finance", 3)


def _render(request: Request, user, session: Session, error: str | None = None):
    rows = obligations.list_obligations(session)
    due_ids = {r["obligation_id"] for r in obligations.upcoming(session)}
    return templates.TemplateResponse(request, "obligations.html", {
        "user": user, "obligations": rows, "due_ids": due_ids,
        "days_left": {o.id: obligations.days_left(o) for o in rows},
        "error": error,
    })


@router.get("/obligations", response_class=HTMLResponse)
def obligations_page(request: Request, user=Depends(require_login),
                     session: Session = Depends(get_session)):
    return _render(request, user, session)


@router.post("/obligations/add", response_class=HTMLResponse)
def obligations_add(request: Request, name: str = Form(...),
                    due_date: str = Form(...), category: str = Form("other"),
                    jurisdiction: str = Form(""), recurrence: str = Form("none"),
                    notice_days: int = Form(30),
                    user=Depends(_finance), session: Session = Depends(get_session)):
    try:
        obligations.add_obligation(
            session, name=name, due_date=date.fromisoformat(due_date),
            category=category, jurisdiction=jurisdiction or None,
            recurrence=recurrence, notice_days=notice_days, created_by=user.id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/obligations", status_code=303)


@router.post("/obligations/seed", response_class=HTMLResponse)
def obligations_seed(request: Request, user=Depends(_finance),
                     session: Session = Depends(get_session)):
    obligations.seed_us_basics(session, created_by=user.id)
    return RedirectResponse("/obligations", status_code=303)


@router.post("/obligations/{obligation_id}/complete", response_class=HTMLResponse)
def obligations_complete(request: Request, obligation_id: int,
                         user=Depends(_finance),
                         session: Session = Depends(get_session)):
    try:
        obligations.complete_obligation(session, obligation_id, user=user)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/obligations", status_code=303)


@router.post("/obligations/{obligation_id}/dismiss", response_class=HTMLResponse)
def obligations_dismiss(request: Request, obligation_id: int,
                        reason: str = Form(""), user=Depends(_finance),
                        session: Session = Depends(get_session)):
    try:
        obligations.dismiss_obligation(session, obligation_id, user=user,
                                       reason=reason)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/obligations", status_code=303)
