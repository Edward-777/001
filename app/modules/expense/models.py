"""Expense / reimbursement (SCHEMA §K). The travel-request endpoint.

An expense claim REUSES the generic approval workflow: it is a 1:1 extension of
a `requests` row (type=expense). On approval -> Dr expense / Cr Employee Payable;
reimbursement -> Dr Employee Payable / Cr Cash.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

Money = Numeric(15, 2)


class ExpenseType(StrEnum):
    TRAVEL = "travel"
    REIMBURSEMENT = "reimbursement"
    ADVANCE = "advance"


class ExpenseStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


class ExpenseCategory(PKMixin, TimestampMixin, Base):
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Maps to an expense account; the posting engine debits this on approval.
    default_expense_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )


class ExpenseClaim(PKMixin, TimestampMixin, Base):
    """1:1 extension of a `requests` row (type=expense) — carries only the
    expense-specific attributes; approval line/amount live on the request."""

    __tablename__ = "expense_claims"

    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    expense_type: Mapped[str] = mapped_column(String(16), nullable=False, default=ExpenseType.REIMBURSEMENT)
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ExpenseStatus.DRAFT)

    lines: Mapped[list[ExpenseLine]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ExpenseLine(PKMixin, Base):
    __tablename__ = "expense_lines"

    expense_claim_id: Mapped[int] = mapped_column(ForeignKey("expense_claims.id"), nullable=False)
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    attachment_path: Mapped[str | None] = mapped_column(String(400), nullable=True)

    claim: Mapped[ExpenseClaim] = relationship(back_populates="lines")


class Reimbursement(PKMixin, TimestampMixin, Base):
    __tablename__ = "reimbursements"

    reimbursement_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    expense_claim_id: Mapped[int] = mapped_column(ForeignKey("expense_claims.id"), nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
