"""Bank reconciliation (SCHEMA §J). Fully local: a monthly statement is UPLOADED
(PDF/CSV), its lines extracted, then matched to existing journal lines. No live
bank feed (that would route credentials through a cloud aggregator — DESIGN).
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

from ...core.money import Money  # noqa: E402


class StatementStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    RECONCILED = "reconciled"


class LineMatchStatus(StrEnum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    NEW_JE = "new_je"


class BankAccount(PKMixin, TimestampMixin, Base):
    __tablename__ = "bank_accounts"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_no_masked: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gl_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")


class BankStatement(PKMixin, TimestampMixin, Base):
    __tablename__ = "bank_statements"

    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    opening_balance: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    closing_balance: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    source_file_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=StatementStatus.UPLOADED)

    lines: Mapped[list[BankStatementLine]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )


class BankStatementLine(PKMixin, Base):
    __tablename__ = "bank_statement_lines"

    statement_id: Mapped[int] = mapped_column(ForeignKey("bank_statements.id"), nullable=False)
    txn_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)  # memo line (AI-parsed)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)  # +deposit / -withdrawal
    matched_journal_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_lines.id"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=LineMatchStatus.UNMATCHED
    )

    statement: Mapped[BankStatement] = relationship(back_populates="lines")
