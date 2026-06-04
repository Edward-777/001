"""ai.conversations — store/load chat turns and rebuild context for the agent.

Short-term memory = the recent slice of this conversation, re-sent each turn
(sliding window). Long-term knowledge stays in the DB/RAG, never here (§8.1)."""
from __future__ import annotations

import json

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..auth.models import Role, User
from . import llm
from .conversation_models import Conversation, Message

_WINDOW = 20  # how many recent messages to keep verbatim in context
_SUMMARY_SYSTEM = (
    "You maintain a running summary of an ERP assistant conversation. Update the "
    "summary so it preserves key facts, decisions, names, numbers, document IDs, and "
    "open items. Be concise (a short paragraph). Output only the updated summary."
)


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


def _fold_old_messages(session: Session, conversation: Conversation, window_start_id: int) -> None:
    """Fold messages that have scrolled out of the live window into the rolling
    summary (incremental — only the newly-dropped ones), so long chats keep their
    earlier context without re-sending everything (memory scaling)."""
    to_fold = session.scalars(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.id > conversation.summarized_upto_id,
            Message.id < window_start_id,
        ).order_by(Message.id)
    ).all()
    if not to_fold:
        return
    transcript = "\n".join(f"{m.role}: {m.content}" for m in to_fold)
    prior = f"Current summary:\n{conversation.summary}\n\n" if conversation.summary else ""
    try:
        msg = llm.chat([
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": f"{prior}New turns to fold in:\n{transcript}"},
        ])
        conversation.summary = (msg.get("content") or conversation.summary or "").strip()
        conversation.summarized_upto_id = to_fold[-1].id
        session.flush()
    except Exception:
        pass  # summarization is best-effort; never break a chat turn


def history_for_llm(session: Session, conversation_id: int) -> list[dict]:
    """Recent turns verbatim, prefixed by a rolling summary of older turns once the
    conversation grows past the window. Re-sending prior turns is what makes the
    assistant 'remember' (LLMs are stateless)."""
    recent = list(reversed(session.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.id)).limit(_WINDOW)
    ).all()))
    out: list[dict] = []
    if recent:
        conv = session.get(Conversation, conversation_id)
        _fold_old_messages(session, conv, recent[0].id)
        if conv.summary:
            out.append({"role": "system",
                        "content": f"Summary of earlier conversation: {conv.summary}"})
    out.extend({"role": m.role, "content": m.content} for m in recent)
    return out


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
