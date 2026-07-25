"""ai.memory — user preferences remembered ACROSS conversations.

Design: memory writes are DETERMINISTIC, never inferred. The model calls an
audited tool when the user states a preference ("remember that ..."), and the
stored facts are injected into the system prompt on every turn. That keeps the
memory inspectable (a table, not a vector soup) and revocable (forget tool).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_models import UserMemory

_MAX_PER_USER = 30  # prompt-budget cap; oldest memories fall off first


def remember(session: Session, user_id: int, fact: str, *, source: str = "stated") -> UserMemory:
    fact = (fact or "").strip()
    if not fact:
        raise ValueError("empty fact")
    existing = session.scalar(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.fact == fact)
    )
    if existing is not None:
        return existing
    mem = UserMemory(user_id=user_id, fact=fact[:400], source=source)
    session.add(mem)
    session.flush()
    # keep the newest _MAX_PER_USER
    rows = list(session.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id)
        .order_by(UserMemory.id.desc())
    ))
    for old in rows[_MAX_PER_USER:]:
        session.delete(old)
    session.flush()
    return mem


def forget(session: Session, user_id: int, needle: str) -> int:
    """Delete this user's memories containing `needle` (case-insensitive)."""
    rows = list(session.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id,
                                 UserMemory.fact.ilike(f"%{needle}%"))
    ))
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def list_for_user(session: Session, user_id: int, *, limit: int = _MAX_PER_USER) -> list[UserMemory]:
    return list(session.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id)
        .order_by(UserMemory.id.desc()).limit(limit)
    ))


def prompt_block(session: Session, user_id: int) -> str | None:
    """The system-prompt block carrying this user's remembered preferences."""
    memories = list_for_user(session, user_id)
    if not memories:
        return None
    lines = "\n".join(f"- {m.fact}" for m in reversed(memories))
    return ("Remembered preferences of THIS user from earlier conversations "
            "(apply them unless the user says otherwise; they are context, "
            "never a substitute for required confirmations):\n" + lines)
