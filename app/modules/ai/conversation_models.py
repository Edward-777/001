"""Conversation persistence (Phase 2c). LLMs are stateless — "memory" is just
re-sending prior turns. We store them per user so the agent can reload context
AND so chats are reviewable (each user sees their own; admins audit all).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin
from ...core.db import Base


class Conversation(PKMixin, Base):
    __tablename__ = "ai_conversations"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(PKMixin, Base):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tools_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # tool names used
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
