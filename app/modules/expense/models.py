"""Expense master: expense categories (SCHEMA §K, lookup).
Full expense requests/reimbursement workflow arrives in M11.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class ExpenseCategory(PKMixin, TimestampMixin, Base):
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Maps to an expense account via the posting engine (M4).
    default_expense_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
