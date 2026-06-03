"""approval.service — create/submit requests, org-chart routing, approve/reject.

On submit, the approval line is built by climbing the requester's reports_to
chain (hr.get_approval_chain) per the matched ApprovalRule's amount band.
When fully approved, emits RequestApproved (M6 turns purchase requests into POs).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.events import bus
from ...core.sequences import next_number
from ..auth.models import User
from ..hr import service as hr
from ..notifications import service as notify
from .events import RequestApproved
from .models import (
    ApprovalLine,
    ApprovalRule,
    ApprovalStatus,
    Request,
    RequestLine,
    RequestStatus,
    RequestType,
    Routing,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- create / submit ----------------------------------------------------

def create_request(
    session: Session,
    *,
    type: RequestType,
    requester_id: int,
    title: str,
    description: str | None = None,
    department_id: int | None = None,
    lines: list[dict] | None = None,
) -> Request:
    """lines: [{description, qty, unit_price, product_id?}]. total = Σ qty*price."""
    req = Request(
        request_no=next_number(session, "REQ", _now().year),
        type=str(type),
        requester_id=requester_id,
        department_id=department_id,
        title=title,
        description=description,
        status=str(RequestStatus.DRAFT),
        total_amount=Decimal("0"),
    )
    session.add(req)
    session.flush()

    total = Decimal("0")
    for ln in lines or []:
        qty = Decimal(str(ln.get("qty", 1)))
        price = Decimal(str(ln.get("unit_price", 0)))
        amount = (qty * price).quantize(Decimal("0.01"))
        total += amount
        session.add(
            RequestLine(
                request_id=req.id,
                product_id=ln.get("product_id"),
                description=ln.get("description"),
                qty=qty,
                estimated_unit_price=price,
                amount=amount,
            )
        )
    req.total_amount = total
    session.flush()
    return req


def _match_rule(session: Session, req_type: str, amount: Decimal) -> ApprovalRule | None:
    rules = session.scalars(
        select(ApprovalRule).where(ApprovalRule.applies_to_type == req_type)
    ).all()
    for r in rules:
        lo = Decimal(str(r.min_amount))
        hi = None if r.max_amount is None else Decimal(str(r.max_amount))
        if amount >= lo and (hi is None or amount < hi):
            return r
    return None


def _resolve_approvers(session: Session, req: Request, rule: ApprovalRule | None) -> list[int]:
    """Return ordered approver user_ids."""
    routing = Routing(rule.routing) if rule else Routing.ORG_CHART

    if routing == Routing.ORG_CHART:
        levels = rule.climb_levels if rule else 1
        emp = hr.get_employee_by_user(session, req.requester_id)
        if emp is None:
            return []
        chain = hr.get_approval_chain(session, emp.id, levels)
        return [m.user_id for m in chain if m.user_id]

    if routing == Routing.FIXED_EMPLOYEE and rule.fixed_employee_id:
        emp = hr.get_employee(session, rule.fixed_employee_id)
        return [emp.user_id] if emp and emp.user_id else []

    if routing == Routing.FIXED_ROLE and rule.fixed_role:
        users = session.scalars(
            select(User).where(User.role == rule.fixed_role, User.is_active.is_(True))
        ).all()
        return [u.id for u in users[:1]]

    return []


def submit_request(session: Session, request_id: int) -> Request:
    req = session.get(Request, request_id)
    if req is None or req.status != RequestStatus.DRAFT:
        raise ValueError("request not in draft")

    rule = _match_rule(session, req.type, Decimal(str(req.total_amount)))
    approvers = _resolve_approvers(session, req, rule)

    for i, user_id in enumerate(approvers, start=1):
        session.add(
            ApprovalLine(
                request_id=req.id,
                approver_id=user_id,
                step_no=i,
                status=str(ApprovalStatus.PENDING),
            )
        )
    req.status = str(RequestStatus.SUBMITTED)
    req.submitted_at = _now()
    session.flush()

    # No one above the requester (e.g. top of org) -> nothing to approve.
    if not approvers:
        _finalize_approved(session, req)
    else:
        notify.notify(session, user_id=approvers[0], type="approval",
                      title=f"Approval needed: {req.title}",
                      body=f"{req.request_no} (${req.total_amount})", link=f"/requests/{req.id}")
    return req


# ---- approve / reject ---------------------------------------------------

def _lines(session: Session, request_id: int) -> list[ApprovalLine]:
    return list(
        session.scalars(
            select(ApprovalLine)
            .where(ApprovalLine.request_id == request_id)
            .order_by(ApprovalLine.step_no)
        )
    )


def _current_step(lines: list[ApprovalLine]) -> ApprovalLine | None:
    return next((ln for ln in lines if ln.status == ApprovalStatus.PENDING), None)


def approve(session: Session, request_id: int, approver_user_id: int, *, comment: str | None = None) -> Request:
    req = session.get(Request, request_id)
    if req is None or req.status != RequestStatus.SUBMITTED:
        raise ValueError("request not awaiting approval")
    lines = _lines(session, request_id)
    current = _current_step(lines)
    if current is None:
        raise ValueError("nothing pending")
    if current.approver_id != approver_user_id:
        raise PermissionError("not your turn to approve")

    current.status = str(ApprovalStatus.APPROVED)
    current.comment = comment
    current.decided_at = _now()
    session.flush()

    nxt = _current_step(lines)
    if nxt is None:  # no more pending
        _finalize_approved(session, req)
    else:
        notify.notify(session, user_id=nxt.approver_id, type="approval",
                      title=f"Approval needed: {req.title}",
                      body=f"{req.request_no} (${req.total_amount})", link=f"/requests/{req.id}")
    return req


def reject(session: Session, request_id: int, approver_user_id: int, *, comment: str | None = None) -> Request:
    req = session.get(Request, request_id)
    if req is None or req.status != RequestStatus.SUBMITTED:
        raise ValueError("request not awaiting approval")
    current = _current_step(_lines(session, request_id))
    if current is None or current.approver_id != approver_user_id:
        raise PermissionError("not your turn to approve")

    current.status = str(ApprovalStatus.REJECTED)
    current.comment = comment
    current.decided_at = _now()
    req.status = str(RequestStatus.REJECTED)
    req.decided_at = _now()
    session.flush()
    notify.notify(session, user_id=req.requester_id, type="rejection",
                  title=f"Rejected: {req.title}",
                  body=comment or req.request_no, link=f"/requests/{req.id}")
    return req


def _finalize_approved(session: Session, req: Request) -> None:
    req.status = str(RequestStatus.APPROVED)
    req.decided_at = _now()
    session.flush()
    notify.notify(session, user_id=req.requester_id, type="approval",
                  title=f"Approved: {req.title}",
                  body=req.request_no, link=f"/requests/{req.id}")

    req_lines = session.scalars(
        select(RequestLine).where(RequestLine.request_id == req.id)
    ).all()
    snapshot = [
        {
            "product_id": ln.product_id,
            "description": ln.description,
            "qty": Decimal(str(ln.qty)),
            "unit_price": Decimal(str(ln.estimated_unit_price)),
        }
        for ln in req_lines
    ]
    bus.emit(
        RequestApproved(
            request_id=req.id,
            request_type=req.type,
            requester_id=req.requester_id,
            total_amount=Decimal(str(req.total_amount)),
            lines=snapshot,
        ),
        session,
    )


# ---- seed ---------------------------------------------------------------

def seed_approval_rules(session: Session) -> int:
    """Default org-chart bands: bigger amount climbs higher (idempotent-ish)."""
    if session.scalar(select(ApprovalRule).limit(1)) is not None:
        return 0
    defaults = [
        # (type, min, max, climb_levels)
        (RequestType.PURCHASE, 0, 1000, 1),
        (RequestType.PURCHASE, 1000, 10000, 2),
        (RequestType.PURCHASE, 10000, None, 3),
        (RequestType.EXPENSE, 0, 1000, 1),
        (RequestType.EXPENSE, 1000, None, 2),
        (RequestType.TRIP, 0, None, 1),
        (RequestType.GENERAL, 0, None, 1),
    ]
    for type_, lo, hi, levels in defaults:
        session.add(
            ApprovalRule(
                applies_to_type=str(type_),
                min_amount=lo,
                max_amount=hi,
                routing=str(Routing.ORG_CHART),
                climb_levels=levels,
            )
        )
    session.flush()
    return len(defaults)
