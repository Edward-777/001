"""Autonomy policies — the envelopes a human signs. Activation/suspension is
the whole point of the page, so everything mutating sits at finance L3."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.policy import service as policy
from .deps import require_login, require_scope, templates

router = APIRouter()
_finance = require_scope("finance", 3)


def _render(request: Request, user, session: Session, error: str | None = None):
    return templates.TemplateResponse(request, "policies.html", {
        "user": user, "policies": policy.list_policies(session),
        "decisions": policy.recent_decisions(session), "error": error,
    })


@router.get("/policies", response_class=HTMLResponse)
def policies_page(request: Request, user=Depends(require_login),
                  session: Session = Depends(get_session)):
    return _render(request, user, session)


@router.post("/policies/propose", response_class=HTMLResponse)
def policies_propose(request: Request, name: str = Form(...),
                     max_amount: float = Form(...), daily_cap: str = Form(""),
                     vendor_allowlisted: bool = Form(False),
                     budget_headroom: bool = Form(False),
                     effective_to: str = Form(""),
                     user=Depends(_finance),
                     session: Session = Depends(get_session)):
    conditions: dict = {"max_amount": max_amount}
    if daily_cap:
        conditions["daily_cap"] = float(daily_cap)
    if vendor_allowlisted:
        conditions["vendor_allowlisted"] = True
    if budget_headroom:
        conditions["budget_headroom"] = True
    try:
        policy.propose_policy(
            session, name=name, action_scope="spend.approve_bill",
            conditions=conditions,
            effective_to=date.fromisoformat(effective_to) if effective_to else None,
            proposed_by=user.id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/policies", status_code=303)


@router.post("/policies/{policy_id}/activate", response_class=HTMLResponse)
def policies_activate(request: Request, policy_id: int, user=Depends(_finance),
                      session: Session = Depends(get_session)):
    try:
        policy.activate_policy(session, policy_id, user=user)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/policies", status_code=303)


@router.post("/policies/{policy_id}/suspend", response_class=HTMLResponse)
def policies_suspend(request: Request, policy_id: int, user=Depends(_finance),
                     session: Session = Depends(get_session)):
    try:
        policy.suspend_policy(session, policy_id, reason="suspended by human",
                              user_id=user.id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/policies", status_code=303)
