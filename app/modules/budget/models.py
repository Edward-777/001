"""budget.models — one row per (expense account, year): the monthly amount.

Actuals are never stored — they are always derived from posted journal lines,
so budget-vs-actual can't drift from the books.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base
from ...core.money import Money


class Budget(PKMixin, TimestampMixin, Base):
    __tablename__ = "budgets"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_amount: Mapped[float] = mapped_column(Money, nullable=False)
