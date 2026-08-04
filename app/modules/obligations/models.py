"""obligations.models — one row per dated duty."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class ObligationCategory(StrEnum):
    TAX = "tax"
    FILING = "filing"
    RENEWAL = "renewal"
    LABOR = "labor"
    INSURANCE = "insurance"
    OTHER = "other"


class ObligationStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


class Recurrence(StrEnum):
    NONE = "none"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class Obligation(PKMixin, TimestampMixin, Base):
    __tablename__ = "obligations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(12), nullable=False,
                                          default=str(ObligationCategory.OTHER))
    jurisdiction: Mapped[str | None] = mapped_column(String(60), nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    recurrence: Mapped[str] = mapped_column(String(12), nullable=False,
                                            default=str(Recurrence.NONE))
    notice_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(ObligationStatus.OPEN))
    source: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="manual")  # manual | seed
    linked_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    linked_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
