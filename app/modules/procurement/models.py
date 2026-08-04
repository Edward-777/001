"""Procurement: vendors (SCHEMA §A) + purchase orders (SCHEMA §C, M6).

A PO is auto-created (draft) when a purchase request is approved (event-driven),
then issued to a vendor. Receiving against the PO happens in M7 (inbound).
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

from ...core.money import Money  # noqa: E402


class PaymentTerms(StrEnum):
    DUE_ON_RECEIPT = "due_on_receipt"
    NET15 = "net15"
    NET30 = "net30"
    NET60 = "net60"


class POStatus(StrEnum):
    DRAFT = "draft"  # auto-created from an approved request, vendor not yet assigned
    OPEN = "open"  # issued to a vendor
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELED = "canceled"


class Vendor(PKMixin, TimestampMixin, Base):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(40), nullable=True)  # US EIN (1099)
    is_1099: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payment_terms: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentTerms.NET30
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Autonomy tier (policy engine): None = normal; "allowlisted" = a human has
    # approved this vendor for L3 envelopes (vendor_allowlisted condition).
    autonomy_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)


class PurchaseOrder(PKMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    po_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=POStatus.DRAFT)
    subtotal: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    total: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    lines: Mapped[list[POLine]] = relationship(
        back_populates="po", cascade="all, delete-orphan"
    )


class POLine(PKMixin, Base):
    __tablename__ = "po_lines"

    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    qty_ordered: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False, default=0)
    qty_received: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")
