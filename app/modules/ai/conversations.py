"""ai.conversations — store/load chat turns and rebuild context for the agent.

Short-term memory = the recent slice of this conversation, re-sent each turn
(sliding window). Long-term knowledge stays in the DB/RAG, never here (§8.1)."""
from __future__ import annotations

import json

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..auth.models import Role, User
from .conversation_models import Conversation, Message

_WINDOW = 20  # how many recent messages to re-send as context


def get_or_create_active(session: Session, user_id: int) -> Conversation:
    """The user's most recent conversation, or a fresh one."""
    conv = session.scalar(
        select(Conversation).where(Conversation.user_id == user_id)
        .order_by(desc(Conversation.id)).limit(1)
    )
    if conv is None:
        conv = start_new(session, user_id)
    return conv


def start_new(session: Session, user_id: int) -> Conversation:
    conv = Conversation(user_id=user_id)
    session.add(conv)
    session.flush()
    return conv


def add_message(
    session: Session, conversation: Conversation, role: str, content: str,
    *, tools: list[str] | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation.id, role=role, content=content,
        tools_json=json.dumps(tools) if tools else None,
    )
    session.add(msg)
    if role == "user" and not conversation.title:
        conversation.title = content[:80]
    session.flush()
    return msg


def history_for_llm(session: Session, conversation_id: int) -> list[dict]:
    """The last _WINDOW messages as LLM message dicts (oldest first). Re-sending
    the assistant's own prior replies is what lets '그거 주문해줘' resolve."""
    recent = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.id)).limit(_WINDOW)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(recent)]


def messages_of(session: Session, conversation_id: int) -> list[Message]:
    return list(
        session.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
    )


def list_conversations(session: Session, viewer: User) -> list[Conversation]:
    """Own conversations; admins see everyone's (audit — answers 'who chatted')."""
    stmt = select(Conversation).order_by(desc(Conversation.id))
    if Role(viewer.role) != Role.ADMIN:
        stmt = stmt.where(Conversation.user_id == viewer.id)
    return list(session.scalars(stmt))


def get_conversation(session: Session, conversation_id: int, viewer: User) -> Conversation | None:
    """Permission-checked fetch: own, or any if admin (DESIGN §8.5 — same gate
    everywhere). Returns None if not allowed/found."""
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        return None
    if conv.user_id != viewer.id and Role(viewer.role) != Role.ADMIN:
        return None
    return conv
