"""Fixed assets, depreciation, and inventory<->asset reclassification
(SCHEMA §E, E-2). Straight-line depreciation only (DESIGN §5.4)."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

Money = Numeric(15, 2)


class AssetStatus(StrEnum):
    IN_USE = "in_use"
    DISPOSED = "disposed"


class ReclassType(StrEnum):
    INVENTORY_TO_ASSET = "inventory_to_asset"
    ASSET_TO_INVENTORY = "asset_to_inventory"


class FixedAsset(PKMixin, TimestampMixin, Base):
    __tablename__ = "fixed_assets"

    asset_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_inbound_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    acquisition_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    acquisition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    salvage_value: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    accumulated_depreciation: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=AssetStatus.IN_USE)


class DepreciationEntry(PKMixin, Base):
    __tablename__ = "depreciation_entries"

    asset_id: Mapped[int] = mapped_column(ForeignKey("fixed_assets.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    # JE traced via journal_entries.source_type='depreciation', source_id=this.id


class Reclassification(PKMixin, TimestampMixin, Base):
    __tablename__ = "reclassifications"

    reclass_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    reclass_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False, default=1)
    fixed_asset_id: Mapped[int | None] = mapped_column(ForeignKey("fixed_assets.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    accum_depreciation: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    memo: Mapped[str | None] = mapped_column(String(400), nullable=True)
