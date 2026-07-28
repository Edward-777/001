"""Leave / PTO pages: my balance + requests, approvals for managers, and the
HR block (allowances, onboarding checklists). Same service functions the AI
tools call — the UI has no privileged path."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth import service as auth
from ..modules.hr import service as hr
from ..modules.hr.models import Employee
from ..modules.leave import service as leave
from .deps import require_login, templates

router = APIRouter()


def _is_hr(user) -> bool:
    return auth.can_access(auth.get_grants(user), "hr", 2)


def _render(request: Request, user, session: Session, error: str | None = None):
    emp = hr.get_employee_by_user(session, user.id)
    year = date.today().year
    mine, awaiting, bal = [], [], None
    if emp is not None:
        bal = leave.balance(session, emp.id, year)
        mine = leave.list_for_employee(session, emp.id)
        awaiting = leave.pending_for_approver(session, emp.id)
    names = {e.id: e.name for e in session.scalars(select(Employee))}
    onboarding = leave.open_onboarding(session) if _is_hr(user) else []
    onboarding_tasks = {e.id: leave.onboarding_for(session, e.id)
                        for e, _, _ in onboarding}
    return templates.TemplateResponse(request, "leave.html", {
        "user": user, "employee": emp, "year": year, "balance": bal,
        "mine": mine, "awaiting": awaiting, "names": names,
        "is_hr": _is_hr(user), "onboarding": onboarding,
        "onboarding_tasks": onboarding_tasks, "error": error,
    })


@router.get("/leave", response_class=HTMLResponse)
def leave_page(request: Request, user=Depends(require_login),
               session: Session = Depends(get_session)):
    return _render(request, user, session)


@router.post("/leave/request", response_class=HTMLResponse)
def leave_request(request: Request, kind: str = Form(...), start_date: str = Form(...),
                  end_date: str = Form(...), reason: str = Form(""),
                  user=Depends(require_login), session: Session = Depends(get_session)):
    emp = hr.get_employee_by_user(session, user.id)
    if emp is None:
        return _render(request, user, session,
                       error="No employee record is linked to your account.")
    try:
        leave.request_leave(session, employee=emp, kind=kind,
                            start_date=date.fromisoformat(start_date),
                            end_date=date.fromisoformat(end_date),
                            reason=reason or None)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/{leave_id}/approve", response_class=HTMLResponse)
def leave_approve(request: Request, leave_id: int, comment: str = Form(""),
                  user=Depends(require_login), session: Session = Depends(get_session)):
    try:
        leave.approve_leave(session, leave_id, user=user, comment=comment or None)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/{leave_id}/deny", response_class=HTMLResponse)
def leave_deny(request: Request, leave_id: int, comment: str = Form(""),
               user=Depends(require_login), session: Session = Depends(get_session)):
    try:
        leave.deny_leave(session, leave_id, user=user, comment=comment or None)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/{leave_id}/cancel", response_class=HTMLResponse)
def leave_cancel(request: Request, leave_id: int, user=Depends(require_login),
                 session: Session = Depends(get_session)):
    try:
        leave.cancel_leave(session, leave_id, user=user)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/allowance", response_class=HTMLResponse)
def leave_allowance(request: Request, employee_no: str = Form(...),
                    allowance_days: float = Form(...),
                    carried_over_days: float = Form(0),
                    user=Depends(require_login),
                    session: Session = Depends(get_session)):
    if not _is_hr(user):
        return _render(request, user, session, error="Requires HR level 2.")
    emp = session.scalar(select(Employee).where(Employee.employee_no == employee_no.strip()))
    if emp is None:
        return _render(request, user, session, error=f"Unknown employee_no {employee_no!r}.")
    try:
        leave.set_allowance(session, employee_id=emp.id, year=date.today().year,
                            allowance_days=allowance_days,
                            carried_over_days=carried_over_days)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/onboarding/start", response_class=HTMLResponse)
def onboarding_start(request: Request, employee_no: str = Form(...),
                     user=Depends(require_login),
                     session: Session = Depends(get_session)):
    if not _is_hr(user):
        return _render(request, user, session, error="Requires HR level 2.")
    emp = session.scalar(select(Employee).where(Employee.employee_no == employee_no.strip()))
    if emp is None:
        return _render(request, user, session, error=f"Unknown employee_no {employee_no!r}.")
    leave.start_onboarding(session, employee=emp)
    return RedirectResponse("/leave", status_code=303)


@router.post("/leave/onboarding/{task_id}/complete", response_class=HTMLResponse)
def onboarding_complete(request: Request, task_id: int, user=Depends(require_login),
                        session: Session = Depends(get_session)):
    if not _is_hr(user):
        return _render(request, user, session, error="Requires HR level 2.")
    try:
        leave.complete_onboarding_task(session, task_id)
    except ValueError as exc:
        return _render(request, user, session, error=str(exc))
    return RedirectResponse("/leave", status_code=303)
