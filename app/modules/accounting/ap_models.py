"""Accounts Payable: vendor bills (3-way match) + payments (SCHEMA §F).

The bill match clears the GR/IR accrued at goods receipt (M7):
    Dr GR/IR Clearing / Cr Accounts Payable.
Payment: Dr Accounts Payable / Cr Cash.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

from ...core.money import Money, Qty  # noqa: E402


class APMatchStatus(StrEnum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    EXCEPTION = "exception"


class APBillStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class BillSource(StrEnum):
    MANUAL = "manual"
    AI_PARSED = "ai_parsed"


class PaymentMethod(StrEnum):
    CHECK = "check"
    ACH = "ach"
    CARD = "card"
    WIRE = "wire"


class APBill(PKMixin, TimestampMixin, Base):
    __tablename__ = "ap_bills"

    bill_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    vendor_invoice_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    bill_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    balance: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    match_status: Mapped[str] = mapped_column(String(12), nullable=False, default=APMatchStatus.UNMATCHED)
    match_note: Mapped[str | None] = mapped_column(String(400), nullable=True)  # WHY it (mis)matched
    source: Mapped[str] = mapped_column(String(12), nullable=False, default=BillSource.MANUAL)
    attachment_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=APBillStatus.DRAFT)

    lines: Mapped[list[APBillLine]] = relationship(
        back_populates="bill", cascade="all, delete-orphan"
    )


class APBillLine(PKMixin, Base):
    __tablename__ = "ap_bill_lines"

    ap_bill_id: Mapped[int] = mapped_column(ForeignKey("ap_bills.id"), nullable=False)
    inbound_line_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_lines.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    qty: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    bill: Mapped[APBill] = relationship(back_populates="lines")


class Payment(PKMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    payment_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    method: Mapped[str | None] = mapped_column(String(12), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    applications: Mapped[list[PaymentApplication]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentApplication(PKMixin, Base):
    __tablename__ = "payment_applications"

    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False)
    ap_bill_id: Mapped[int] = mapped_column(ForeignKey("ap_bills.id"), nullable=False)
    applied_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    payment: Mapped[Payment] = relationship(back_populates="applications")
