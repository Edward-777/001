"""Inventory: products/categories (M3) + inbound, stock, serials (M7).

Moving-average valuation at the product level (stock_balances). Inbound posting
updates stock and emits InboundPosted; accounting reacts to post the journal entry.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

Money = Numeric(15, 2)
Qty = Numeric(15, 3)


class ProductType(StrEnum):
    """Drives auto-posting at inbound/outbound (inventory vs asset vs expense)."""

    INVENTORY = "inventory"
    ASSET = "asset"
    CONSUMABLE = "consumable"
    SERVICE = "service"


class ProductCategory(PKMixin, TimestampMixin, Base):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_categories.id"), nullable=True
    )


class Product(PKMixin, TimestampMixin, Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default=ProductType.INVENTORY)
    track_serial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="ea")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_categories.id"), nullable=True
    )
    standard_cost: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    default_expense_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InboundStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"


class MovementType(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    ADJUSTMENT = "adjustment"


class Inbound(PKMixin, TimestampMixin, Base):
    __tablename__ = "inbounds"

    inbound_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=InboundStatus.DRAFT)

    lines: Mapped[list[InboundLine]] = relationship(
        back_populates="inbound", cascade="all, delete-orphan"
    )


class InboundLine(PKMixin, Base):
    __tablename__ = "inbound_lines"

    inbound_id: Mapped[int] = mapped_column(ForeignKey("inbounds.id"), nullable=False)
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty_received: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)

    inbound: Mapped[Inbound] = relationship(back_populates="lines")


class OutboundType(StrEnum):
    SALE = "sale"
    CONSUMPTION = "consumption"
    DISPOSAL = "disposal"
    TRANSFER = "transfer"


class Outbound(PKMixin, TimestampMixin, Base):
    __tablename__ = "outbounds"

    outbound_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(12), nullable=False, default=OutboundType.SALE)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # e.g. 'sales_order'
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memo: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=InboundStatus.DRAFT)

    lines: Mapped[list[OutboundLine]] = relationship(
        back_populates="outbound", cascade="all, delete-orphan"
    )


class OutboundLine(PKMixin, Base):
    __tablename__ = "outbound_lines"

    outbound_id: Mapped[int] = mapped_column(ForeignKey("outbounds.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)  # set at posting
    inventory_serial_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_serials.id"), nullable=True
    )

    outbound: Mapped[Outbound] = relationship(back_populates="lines")


class StockMovement(PKMixin, Base):
    """Append-only inventory ledger (one row per stock change)."""

    __tablename__ = "stock_movements"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(12), nullable=False)
    qty: Mapped[float] = mapped_column(Qty, nullable=False)  # signed: + in, - out
    unit_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # inbound/outbound/reclass
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StockBalance(PKMixin, Base):
    """Current on-hand + moving-average cost — one row per product."""

    __tablename__ = "stock_balances"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    qty_on_hand: Mapped[float] = mapped_column(Qty, nullable=False, default=0)
    avg_unit_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    total_value: Mapped[float] = mapped_column(Money, nullable=False, default=0)


class SerialStatus(StrEnum):
    IN_STOCK = "in_stock"
    SOLD = "sold"
    SCRAPPED = "scrapped"


class InventorySerial(PKMixin, Base):
    """Per-unit tracking for track_serial products (SCHEMA §A). Valuation stays
    moving-average; serials record WHICH units are on hand. Populated from M7+."""

    __tablename__ = "inventory_serials"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    serial_no: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=SerialStatus.IN_STOCK)
    unit_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    inbound_line_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_lines.id"), nullable=True)
    outbound_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
