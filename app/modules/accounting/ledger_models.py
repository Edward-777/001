"""Double-entry ledger + periods + posting rules (SCHEMA §F,H; ARCHITECTURE §4).

Separate from master models.py: this is the transactional core every module
posts into via the event bus.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

from ...core.money import Money  # noqa: E402


class JournalStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class JournalSource(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    ASSET = "asset"
    RECLASS = "reclass"
    AP_BILL = "ap_bill"
    PAYMENT = "payment"
    AR_INVOICE = "ar_invoice"
    RECEIPT = "receipt"
    EXPENSE = "expense"
    BANK = "bank"
    DEPRECIATION = "depreciation"
    MANUAL = "manual"


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class JournalEntry(PKMixin, TimestampMixin, Base):
    __tablename__ = "journal_entries"

    je_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default=JournalSource.MANUAL)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=JournalStatus.POSTED)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    reversed_by_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", foreign_keys="JournalLine.je_id"
    )


class JournalLine(PKMixin, Base):
    __tablename__ = "journal_lines"

    je_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    debit: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    credit: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    memo: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # the vendor/customer ("Name") on this line — enables per-vendor AP / spend
    party: Mapped[str | None] = mapped_column(String(160), nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines", foreign_keys=[je_id])


class AccountingPeriod(PKMixin, Base):
    __tablename__ = "accounting_periods"

    period: Mapped[str] = mapped_column(String(7), unique=True, nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(8), nullable=False, default=PeriodStatus.OPEN)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class PostingRule(PKMixin, Base):
    """Configurable event -> accounts mapping (ARCHITECTURE §4). Covers simple
    2-line postings; multi-line events build lines explicitly in their handlers."""

    __tablename__ = "posting_rules"
    __table_args__ = (UniqueConstraint("event_type", "condition", name="uq_posting_rule"),)

    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    condition: Mapped[str | None] = mapped_column(String(40), nullable=True)  # e.g. product_type
    debit_role: Mapped[str] = mapped_column(String(40), nullable=False)
    credit_role: Mapped[str] = mapped_column(String(40), nullable=False)
