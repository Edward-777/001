"""Accounting master: chart of accounts + tax codes (SCHEMA §A accounts, tax_codes).

`system_role` gives the posting engine (M4) a STABLE handle for default postings
(e.g. 'inventory', 'gr_ir', 'ap') independent of the numeric code, while admins
can still renumber/remap. Posting rules (M4) reference accounts by role or id.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class Account(PKMixin, TimestampMixin, Base):
    __tablename__ = "accounts"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    # Stable semantic anchor for auto-posting (nullable; unique when set).
    system_role: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TaxCode(PKMixin, TimestampMixin, Base):
    __tablename__ = "tax_codes"

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0)  # percent
    tax_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
