"""fleet.service — public API for the work queue (docs/AGENT-FLEET.md §3).

The single work loop and the dispatcher go through these functions only; the
state machine (queued → in_progress → done/needs_approval/bounced/failed) lives
here so transitions are consistent and auditable.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    BOUNCE_ESCALATION_LIMIT,
    Role,
    Task,
    TaskSource,
    TaskStatus,
)


def enqueue(
    session: Session,
    *,
    to_role: Role | str,
    category: str,
    title: str,
    source: TaskSource | str,
    payload: dict | None = None,
    from_role: Role | str = Role.DISPATCHER,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> Task:
    """Add a unit of work. If `idempotency_key` is given and already present,
    the existing task is returned (so a re-running schedule can't double-enqueue)."""
    if idempotency_key:
        existing = session.scalar(
            select(Task).where(Task.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
    task = Task(
        source=str(source),
        source_ref=source_ref,
        category=category,
        from_role=str(from_role),
        to_role=str(to_role),
        title=title,
        payload=payload or {},
        status=str(TaskStatus.QUEUED),
        idempotency_key=idempotency_key,
    )
    session.add(task)
    session.flush()
    return task


def next_queued(session: Session, *, to_role: Role | str | None = None) -> Task | None:
    """The oldest queued task (optionally for one role) — what the loop claims next."""
    stmt = select(Task).where(Task.status == str(TaskStatus.QUEUED))
    if to_role is not None:
        stmt = stmt.where(Task.to_role == str(to_role))
    return session.scalars(stmt.order_by(Task.id)).first()


def claim(session: Session, task: Task) -> Task:
    """Mark a task in-progress (the loop picked it up)."""
    task.status = str(TaskStatus.IN_PROGRESS)
    session.flush()
    return task


def complete(session: Session, task: Task, *, result: dict | None = None) -> Task:
    task.status = str(TaskStatus.DONE)
    if result is not None:
        task.result = result
    session.flush()
    return task


def request_approval(
    session: Session, task: Task, *, approval_id: int | None = None,
    result: dict | None = None,
) -> Task:
    """Park a task for the founder — a draft is ready but posting/pay/send needs
    a human OK (the universal gate, AGENT-FLEET §5)."""
    task.status = str(TaskStatus.NEEDS_APPROVAL)
    if approval_id is not None:
        task.approval_id = approval_id
    if result is not None:
        task.result = result
    session.flush()
    return task


def fail(session: Session, task: Task, *, reason: str) -> Task:
    task.status = str(TaskStatus.FAILED)
    task.bounce_reason = reason  # reuse the reason column for the failure note
    session.flush()
    return task


def bounce(session: Session, task: Task, *, reason: str) -> Task:
    """A role says 'not mine'. Bumps the counter and parks the task. Past the
    escalation limit it goes to the founder instead of bouncing forever."""
    task.bounce_count += 1
    task.bounce_reason = reason
    if task.bounce_count >= BOUNCE_ESCALATION_LIMIT:
        task.status = str(TaskStatus.NEEDS_APPROVAL)  # escalate to the founder
    else:
        task.status = str(TaskStatus.BOUNCED)
    session.flush()
    return task


def reroute(session: Session, task: Task, *, to_role: Role | str) -> Task:
    """The dispatcher re-assigns a bounced task to a different role and re-queues."""
    task.to_role = str(to_role)
    task.from_role = str(Role.DISPATCHER)
    task.status = str(TaskStatus.QUEUED)
    session.flush()
    return task


def resolve_approval(session: Session, task: Task, *, approved: bool) -> Task:
    """Founder decision on a parked task: approved → done, rejected → failed.
    (The caller does the actual posting/side-effect before marking done.)"""
    task.status = str(TaskStatus.DONE if approved else TaskStatus.FAILED)
    session.flush()
    return task


def get_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def list_tasks(
    session: Session, *, status: TaskStatus | str | None = None,
    to_role: Role | str | None = None,
) -> list[Task]:
    stmt = select(Task)
    if status is not None:
        stmt = stmt.where(Task.status == str(status))
    if to_role is not None:
        stmt = stmt.where(Task.to_role == str(to_role))
    return list(session.scalars(stmt.order_by(Task.id.desc())))


def pending_approvals(session: Session) -> list[Task]:
    """Everything waiting on the founder — the approval inbox."""
    return list(
        session.scalars(
            select(Task)
            .where(Task.status == str(TaskStatus.NEEDS_APPROVAL))
            .order_by(Task.id)
        )
    )
