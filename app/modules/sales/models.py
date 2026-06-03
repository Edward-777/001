"""Sales / AR (SCHEMA §I, mirror of vendors/AP): customers, sales orders,
customer invoices, receipts. M9."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

from ...core.money import Money, Qty  # noqa: E402


class SOStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    SHIPPED = "shipped"
    INVOICED = "invoiced"
    CLOSED = "closed"


class ARStatus(StrEnum):
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class Customer(PKMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ar_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SalesOrder(PKMixin, TimestampMixin, Base):
    __tablename__ = "sales_orders"

    so_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=SOStatus.OPEN)

    lines: Mapped[list[SOLine]] = relationship(back_populates="so", cascade="all, delete-orphan")


class SOLine(PKMixin, Base):
    __tablename__ = "so_lines"

    so_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    qty_ordered: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    qty_shipped: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    so: Mapped[SalesOrder] = relationship(back_populates="lines")


class ARInvoice(PKMixin, TimestampMixin, Base):
    __tablename__ = "ar_invoices"

    invoice_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    so_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    tax_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    total: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    balance: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ARStatus.OPEN)

    lines: Mapped[list[ARInvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class ARInvoiceLine(PKMixin, Base):
    __tablename__ = "ar_invoice_lines"

    ar_invoice_id: Mapped[int] = mapped_column(ForeignKey("ar_invoices.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    qty: Mapped[float] = mapped_column(Qty, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    invoice: Mapped[ARInvoice] = relationship(back_populates="lines")


class Receipt(PKMixin, TimestampMixin, Base):
    __tablename__ = "receipts"

    receipt_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    applications: Mapped[list[ReceiptApplication]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class ReceiptApplication(PKMixin, Base):
    __tablename__ = "receipt_applications"

    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), nullable=False)
    ar_invoice_id: Mapped[int] = mapped_column(ForeignKey("ar_invoices.id"), nullable=False)
    applied_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    receipt: Mapped[Receipt] = relationship(back_populates="applications")
