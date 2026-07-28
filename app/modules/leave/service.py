"""leave.service — public API for PTO and onboarding.

Rules:
- `used` is always derived from APPROVED vacation requests — never stored — so
  the balance cannot drift from the requests that consumed it.
- A request routes to the immediate manager (reports_to). No manager (the
  founder) -> auto-approved, stated openly on the record.
- Only vacation draws down the balance; sick/unpaid are tracked, not gated.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ..auth.models import Role, User
from ..documents.models import Document
from ..hr import service as hr
from ..hr.models import Employee
from ..notifications import service as notify
from .models import (
    DEFAULT_ONBOARDING,
    LeaveKind,
    LeaveRequest,
    LeaveStatus,
    OnboardingTask,
    PtoBalance,
)


def business_days(start: date, end: date) -> float:
    """Weekdays in [start, end], inclusive. Holidays are not modeled (v1)."""
    days, current = 0, start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return float(days)


# ---- balances -------------------------------------------------------------

def set_allowance(session: Session, *, employee_id: int, year: int,
                  allowance_days: float, carried_over_days: float = 0) -> PtoBalance:
    if session.get(Employee, employee_id) is None:
        raise ValueError("employee not found")
    if allowance_days < 0 or carried_over_days < 0:
        raise ValueError("allowance and carryover must be >= 0")
    row = session.scalar(select(PtoBalance).where(
        PtoBalance.employee_id == employee_id, PtoBalance.year == year))
    if row is None:
        row = PtoBalance(employee_id=employee_id, year=year)
        session.add(row)
    row.allowance_days = allowance_days
    row.carried_over_days = carried_over_days
    session.flush()
    return row


def _vacation_days(session: Session, employee_id: int, year: int,
                   status: LeaveStatus, exclude_id: int | None = None) -> Decimal:
    stmt = select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.kind == str(LeaveKind.VACATION),
        LeaveRequest.status == str(status))
    total = Decimal("0")
    for r in session.scalars(stmt):
        if r.start_date.year == year and r.id != exclude_id:
            total += Decimal(str(r.days))
    return total


def balance(session: Session, employee_id: int, year: int) -> dict:
    row = session.scalar(select(PtoBalance).where(
        PtoBalance.employee_id == employee_id, PtoBalance.year == year))
    granted = (Decimal(str(row.allowance_days)) + Decimal(str(row.carried_over_days))
               if row else Decimal("0"))
    used = _vacation_days(session, employee_id, year, LeaveStatus.APPROVED)
    pending = _vacation_days(session, employee_id, year, LeaveStatus.PENDING)
    return {
        "year": year,
        "granted": float(granted),
        "used": float(used),
        "pending": float(pending),
        "available": float(granted - used - pending),
        "allowance_set": row is not None,
    }


# ---- leave requests -------------------------------------------------------

def _overlaps(session: Session, employee_id: int, start: date, end: date) -> LeaveRequest | None:
    stmt = select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.status.in_([str(LeaveStatus.PENDING), str(LeaveStatus.APPROVED)]),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start)
    return session.scalars(stmt).first()


def request_leave(session: Session, *, employee: Employee, kind: str,
                  start_date: date, end_date: date,
                  reason: str | None = None) -> LeaveRequest:
    if kind not in {k.value for k in LeaveKind}:
        raise ValueError(f"kind must be one of {[k.value for k in LeaveKind]}")
    if end_date < start_date:
        raise ValueError("end_date is before start_date")
    days = business_days(start_date, end_date)
    if days <= 0:
        raise ValueError("the selected range contains no business days")
    clash = _overlaps(session, employee.id, start_date, end_date)
    if clash is not None:
        raise ValueError(f"overlaps an existing {clash.status} request "
                         f"({clash.start_date} – {clash.end_date})")
    if kind == LeaveKind.VACATION:
        bal = balance(session, employee.id, start_date.year)
        if not bal["allowance_set"]:
            raise ValueError(f"no PTO allowance set for {start_date.year} — "
                             "ask HR to set it first")
        if days > bal["available"]:
            raise ValueError(f"insufficient PTO: requesting {days:g} days but only "
                             f"{bal['available']:g} available "
                             f"(granted {bal['granted']:g}, used {bal['used']:g}, "
                             f"pending {bal['pending']:g})")

    approvers = hr.get_approval_chain(session, employee.id, 1)
    approver = approvers[0] if approvers else None
    req = LeaveRequest(
        employee_id=employee.id, kind=kind, start_date=start_date,
        end_date=end_date, days=days, reason=reason,
        approver_employee_id=approver.id if approver else None)
    if approver is None:
        # top of the org chart — no one to route to; say so on the record
        req.status = str(LeaveStatus.APPROVED)
        req.decided_at = datetime.now(timezone.utc)
        req.decision_comment = "auto-approved: no manager above requester"
    session.add(req)
    session.flush()
    if approver is not None and approver.user_id is not None:
        notify.notify(session, user_id=approver.user_id, type="leave_request",
                      title=f"Leave request: {employee.name}",
                      body=f"{kind} {start_date} – {end_date} ({days:g} business days)",
                      link="/leave")
    audit.record(session, actor_user_id=employee.user_id, action="create",
                 entity_type="leave_request", entity_id=req.id,
                 detail={"kind": kind, "days": days})
    return req


def _may_decide(session: Session, req: LeaveRequest, user: User) -> bool:
    if user.role == Role.ADMIN:
        return True
    actor_emp = hr.get_employee_by_user(session, user.id)
    return actor_emp is not None and actor_emp.id == req.approver_employee_id


def _decide(session: Session, request_id: int, *, user: User, approve: bool,
            comment: str | None) -> LeaveRequest:
    req = session.get(LeaveRequest, request_id)
    if req is None:
        raise ValueError("leave request not found")
    if req.status != str(LeaveStatus.PENDING):
        raise ValueError(f"request is '{req.status}', not pending")
    if not _may_decide(session, req, user):
        raise ValueError("only the assigned approver (or an admin) can decide this")
    if approve and req.kind == str(LeaveKind.VACATION):
        # `available` already nets out this request (it sits in `pending`), so a
        # negative value means the allowance shrank or other leave was approved
        # since this was filed — approving would overdraw the balance.
        if balance(session, req.employee_id, req.start_date.year)["available"] < 0:
            raise ValueError("balance went insufficient since the request was filed")
    req.status = str(LeaveStatus.APPROVED if approve else LeaveStatus.DENIED)
    req.decided_by_user_id = user.id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_comment = comment
    session.flush()
    emp = session.get(Employee, req.employee_id)
    if emp is not None and emp.user_id is not None:
        verdict = "approved" if approve else "denied"
        notify.notify(session, user_id=emp.user_id, type="leave_decision",
                      title=f"Leave {verdict}: {req.start_date} – {req.end_date}",
                      body=comment or "", link="/leave")
    audit.record(session, actor_user_id=user.id,
                 action="approve" if approve else "reject",
                 entity_type="leave_request", entity_id=req.id,
                 detail={"comment": comment})
    return req


def approve_leave(session: Session, request_id: int, *, user: User,
                  comment: str | None = None) -> LeaveRequest:
    return _decide(session, request_id, user=user, approve=True, comment=comment)


def deny_leave(session: Session, request_id: int, *, user: User,
               comment: str | None = None) -> LeaveRequest:
    return _decide(session, request_id, user=user, approve=False, comment=comment)


def cancel_leave(session: Session, request_id: int, *, user: User) -> LeaveRequest:
    req = session.get(LeaveRequest, request_id)
    if req is None:
        raise ValueError("leave request not found")
    emp = hr.get_employee_by_user(session, user.id)
    if emp is None or emp.id != req.employee_id:
        raise ValueError("you can only cancel your own request")
    if req.status != str(LeaveStatus.PENDING):
        raise ValueError(f"request is '{req.status}', not pending")
    req.status = str(LeaveStatus.CANCELED)
    session.flush()
    return req


def list_for_employee(session: Session, employee_id: int) -> list[LeaveRequest]:
    return list(session.scalars(
        select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)
        .order_by(LeaveRequest.start_date.desc())))


def pending_for_approver(session: Session, approver_employee_id: int) -> list[LeaveRequest]:
    return list(session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.approver_employee_id == approver_employee_id,
            LeaveRequest.status == str(LeaveStatus.PENDING))
        .order_by(LeaveRequest.start_date)))


# ---- onboarding checklist -------------------------------------------------

def start_onboarding(session: Session, *, employee: Employee) -> list[OnboardingTask]:
    """Create the default checklist for a new hire. Idempotent."""
    existing = list(session.scalars(select(OnboardingTask).where(
        OnboardingTask.employee_id == employee.id)))
    if existing:
        return existing
    tasks = [OnboardingTask(employee_id=employee.id, title=title, doc_category=cat)
             for title, cat in DEFAULT_ONBOARDING]
    session.add_all(tasks)
    session.flush()
    return tasks


def complete_onboarding_task(session: Session, task_id: int, *,
                             document_id: int | None = None) -> OnboardingTask:
    task = session.get(OnboardingTask, task_id)
    if task is None:
        raise ValueError("onboarding task not found")
    if document_id is not None and session.get(Document, document_id) is None:
        raise ValueError("document not found")
    task.done = True
    task.done_at = datetime.now(timezone.utc)
    if document_id is not None:
        task.document_id = document_id
    session.flush()
    return task


def onboarding_for(session: Session, employee_id: int) -> list[OnboardingTask]:
    return list(session.scalars(
        select(OnboardingTask).where(OnboardingTask.employee_id == employee_id)
        .order_by(OnboardingTask.id)))


def open_onboarding(session: Session) -> list[tuple[Employee, int, int]]:
    """Employees with an unfinished checklist: (employee, done, total)."""
    out: list[tuple[Employee, int, int]] = []
    tasks = list(session.scalars(select(OnboardingTask).order_by(OnboardingTask.id)))
    by_emp: dict[int, list[OnboardingTask]] = {}
    for t in tasks:
        by_emp.setdefault(t.employee_id, []).append(t)
    for emp_id, ts in by_emp.items():
        done = sum(1 for t in ts if t.done)
        if done < len(ts):
            emp = session.get(Employee, emp_id)
            if emp is not None:
                out.append((emp, done, len(ts)))
    return out
