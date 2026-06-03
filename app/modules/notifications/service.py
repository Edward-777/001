"""notifications.service — a small cross-cutting service (like audit). Other
modules call notify() at noteworthy moments; the UI polls/streams these."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Notification


def notify(
    session: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    n = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    session.add(n)
    session.flush()
    return n


def list_for_user(
    session: Session, user_id: int, *, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
    ) or 0


def mark_read(session: Session, notification_id: int) -> None:
    n = session.get(Notification, notification_id)
    if n is not None:
        n.is_read = True
        session.flush()


def mark_all_read(session: Session, user_id: int) -> int:
    from sqlalchemy import update

    result = session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    session.flush()
    return result.rowcount or 0
