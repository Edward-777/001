"""Inventory master: products + categories (SCHEMA §A products, product_categories).
Stock movements/balances, inbound/outbound, serials arrive in M7.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


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
