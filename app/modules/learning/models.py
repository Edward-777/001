"""learning.models — rules the system LEARNED from human resolutions.

A learned rule is a first-class, inspectable record: mined deterministically
from decisions humans already made, proposed as a draft in the approval inbox,
active only after a human approves, and revocable. Learning here means the
system's *behavior* changes — never its weights.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class LearnedRule(PKMixin, TimestampMixin, Base):
    __tablename__ = "learned_rules"

    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # vendor_alias | ...
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
