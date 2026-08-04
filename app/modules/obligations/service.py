"""obligations.service — the compliance calendar.

Completing a recurring obligation immediately creates its next occurrence, so
the calendar is self-perpetuating. The seed catalog is REFERENCE DATA for a
US small business (federal + WA + optional Delaware entity) — a starting
checklist to edit, not tax advice.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ..auth.models import User
from .models import (
    Obligation,
    ObligationCategory,
    ObligationStatus,
    Recurrence,
)


def add_obligation(
    session: Session,
    *,
    name: str,
    due_date: date,
    category: str = str(ObligationCategory.OTHER),
    jurisdiction: str | None = None,
    recurrence: str = str(Recurrence.NONE),
    notice_days: int = 30,
    source: str = "manual",
    linked_type: str | None = None,
    linked_id: int | None = None,
    notes: str | None = None,
    created_by: int | None = None,
) -> Obligation:
    if not (name or "").strip():
        raise ValueError("name is required")
    if category not in {c.value for c in ObligationCategory}:
        raise ValueError(f"category must be one of "
                         f"{[c.value for c in ObligationCategory]}")
    if recurrence not in {r.value for r in Recurrence}:
        raise ValueError(f"recurrence must be one of "
                         f"{[r.value for r in Recurrence]}")
    if notice_days < 0:
        raise ValueError("notice_days must be >= 0")
    o = Obligation(name=name.strip(), category=category,
                   jurisdiction=jurisdiction, due_date=due_date,
                   recurrence=recurrence, notice_days=notice_days,
                   source=source, linked_type=linked_type, linked_id=linked_id,
                   notes=notes)
    session.add(o)
    session.flush()
    audit.record(session, actor_user_id=created_by, action="create",
                 entity_type="obligation", entity_id=o.id,
                 detail={"name": o.name, "due": str(due_date)})
    return o


def _advance(due: date, recurrence: str) -> date:
    """Next occurrence, preserving the day of month. A day past the target
    month's end clamps to that month's last day, so month-end duties (941 due
    Oct 31 -> Jan 31) stay on month-end instead of drifting to the 28th."""
    from calendar import monthrange

    if recurrence == str(Recurrence.MONTHLY):
        months = 1
    elif recurrence == str(Recurrence.QUARTERLY):
        months = 3
    elif recurrence == str(Recurrence.ANNUAL):
        months = 12
    else:
        raise ValueError("not recurring")
    month = due.month + months
    year = due.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, min(due.day, monthrange(year, month)[1]))


def complete_obligation(session: Session, obligation_id: int, *,
                        user: User | None = None,
                        notes: str | None = None) -> Obligation:
    """Mark done — and if recurring, spawn the next occurrence right away."""
    o = session.get(Obligation, obligation_id)
    if o is None:
        raise ValueError("obligation not found")
    if o.status != str(ObligationStatus.OPEN):
        raise ValueError(f"obligation is '{o.status}', not open")
    o.status = str(ObligationStatus.DONE)
    o.completed_at = datetime.now(timezone.utc)
    o.completed_by = user.id if user else None
    if notes:
        o.notes = (f"{o.notes}\n{notes}" if o.notes else notes)[:1000]
    session.flush()
    audit.record(session, actor_user_id=user.id if user else None,
                 action="update", entity_type="obligation", entity_id=o.id,
                 detail={"status": "done"})
    if o.recurrence != str(Recurrence.NONE):
        add_obligation(
            session, name=o.name, due_date=_advance(o.due_date, o.recurrence),
            category=o.category, jurisdiction=o.jurisdiction,
            recurrence=o.recurrence, notice_days=o.notice_days,
            source=o.source, linked_type=o.linked_type, linked_id=o.linked_id,
            created_by=user.id if user else None)
    return o


def dismiss_obligation(session: Session, obligation_id: int, *,
                       user: User | None = None, reason: str = "") -> Obligation:
    """Drop a duty that doesn't apply (no next occurrence is spawned)."""
    o = session.get(Obligation, obligation_id)
    if o is None:
        raise ValueError("obligation not found")
    if o.status != str(ObligationStatus.OPEN):
        raise ValueError(f"obligation is '{o.status}', not open")
    o.status = str(ObligationStatus.DISMISSED)
    if reason:
        o.notes = (f"{o.notes}\ndismissed: {reason}" if o.notes
                   else f"dismissed: {reason}")[:1000]
    session.flush()
    audit.record(session, actor_user_id=user.id if user else None,
                 action="update", entity_type="obligation", entity_id=o.id,
                 detail={"status": "dismissed", "reason": reason})
    return o


def list_obligations(session: Session, *, include_closed: bool = False) -> list[Obligation]:
    stmt = select(Obligation).order_by(Obligation.due_date)
    if not include_closed:
        stmt = stmt.where(Obligation.status == str(ObligationStatus.OPEN))
    return list(session.scalars(stmt))


def days_left(o: Obligation, *, as_of: date | None = None) -> int:
    return (o.due_date - (as_of or date.today())).days


def upcoming(session: Session, *, as_of: date | None = None,
             within_days: int | None = None) -> list[dict]:
    """Open duties inside their notice window (or overdue), soonest first."""
    as_of = as_of or date.today()
    out = []
    for o in list_obligations(session):
        window = within_days if within_days is not None else o.notice_days
        left = days_left(o, as_of=as_of)
        if left <= window:
            out.append({"obligation_id": o.id, "name": o.name,
                        "category": o.category, "jurisdiction": o.jurisdiction,
                        "due_date": str(o.due_date), "days_left": left,
                        "overdue": left < 0, "recurrence": o.recurrence})
    out.sort(key=lambda r: r["due_date"])
    return out


# ---- reference seed (a starting checklist, not tax advice) -------------------

def seed_us_basics(session: Session, *, year: int | None = None,
                   wa: bool = True, delaware_entity: bool = True,
                   created_by: int | None = None) -> list[Obligation]:
    """Idempotent starting calendar for a US small business (federal + WA +
    optional Delaware entity). Each recurring item seeds its NEXT occurrence;
    completion spawns the following one."""
    today = date.today()
    year = year or today.year

    def next_due(month: int, day: int) -> date:
        d = date(year, month, day)
        return d if d >= today else date(year + 1, month, day)

    def next_quarterly() -> date:
        for d in (date(year, 1, 31), date(year, 4, 30), date(year, 7, 31),
                  date(year, 10, 31), date(year + 1, 1, 31)):
            if d >= today:
                return d
        return date(year + 1, 1, 31)

    catalog: list[dict] = [
        dict(name="Form 941 — federal payroll tax return", category="tax",
             jurisdiction="US-Federal", due_date=next_quarterly(),
             recurrence=str(Recurrence.QUARTERLY), notice_days=21),
        dict(name="Form 940 — federal unemployment (FUTA)", category="tax",
             jurisdiction="US-Federal", due_date=next_due(1, 31),
             recurrence=str(Recurrence.ANNUAL), notice_days=30),
        dict(name="1099-NEC — contractor information returns", category="filing",
             jurisdiction="US-Federal", due_date=next_due(1, 31),
             recurrence=str(Recurrence.ANNUAL), notice_days=45),
        dict(name="Form 1120 — federal corporate income tax", category="tax",
             jurisdiction="US-Federal", due_date=next_due(4, 15),
             recurrence=str(Recurrence.ANNUAL), notice_days=60),
    ]
    if wa:
        catalog += [
            dict(name="WA B&O excise return", category="tax",
                 jurisdiction="US-WA", due_date=next_quarterly(),
                 recurrence=str(Recurrence.QUARTERLY), notice_days=21),
            dict(name="WA L&I workers' comp quarterly report", category="labor",
                 jurisdiction="US-WA", due_date=next_quarterly(),
                 recurrence=str(Recurrence.QUARTERLY), notice_days=21),
        ]
    if delaware_entity:
        catalog += [
            dict(name="Delaware franchise tax + annual report", category="filing",
                 jurisdiction="US-DE", due_date=next_due(3, 1),
                 recurrence=str(Recurrence.ANNUAL), notice_days=45),
        ]

    created: list[Obligation] = []
    for item in catalog:
        exists = session.scalar(select(Obligation).where(
            Obligation.name == item["name"],
            Obligation.status == str(ObligationStatus.OPEN)))
        if exists is not None:
            continue
        created.append(add_obligation(session, source="seed",
                                      created_by=created_by, **item))
    return created
