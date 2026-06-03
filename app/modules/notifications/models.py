"""In-app notifications (SCHEMA §A0, POLICIES §G12). Local-first: stored in DB,
pushed live via SSE (the SSE endpoint is added with the UI in M15)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin
from ...core.db import Base


class Notification(PKMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # approval/rejection/ai_question/due
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    link: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
