"""assets.service — fixed assets, straight-line depreciation, and
inventory<->asset reclassification.

GL postings are NOT done here: assets emits events (DepreciationPosted,
Reclassified) and accounting books them. Stock moves via inventory.service
(command calls; inventory never depends on assets, so no cycle)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.events import bus
from ...core.sequences import next_number
from ..inventory import service as inv
from .events import DepreciationPosted, Reclassified
from .models import (
    AssetStatus,
    DepreciationEntry,
    FixedAsset,
    Reclassification,
    ReclassType,
)

_CENTS = Decimal("0.01")


def _now_year() -> int:
    return datetime.now(timezone.utc).year


def _period_date(period: str) -> date:
    y, m = period.split("-")
    return date(int(y), int(m), 28)


# ---- asset creation (called by the inbound handler) ---------------------

def create_asset(
    session: Session,
    *,
    name: str,
    acquisition_cost: Decimal,
    acquisition_date: date | None = None,
    product_id: int | None = None,
    model_name: str | None = None,
    serial_number: str | None = None,
    source_inbound_line_id: int | None = None,
    useful_life_months: int = 60,
    salvage_value: Decimal = Decimal("0"),
) -> FixedAsset:
    acq_date = acquisition_date or date.today()
    asset = FixedAsset(
        asset_no=next_number(session, "FA", acq_date.year),
        name=name,
        model_name=model_name,
        serial_number=serial_number,
        source_inbound_line_id=source_inbound_line_id,
        product_id=product_id,
        acquisition_cost=Decimal(str(acquisition_cost)).quantize(_CENTS),
        acquisition_date=acq_date,
        useful_life_months=useful_life_months,
        salvage_value=Decimal(str(salvage_value)).quantize(_CENTS),
        accumulated_depreciation=Decimal("0"),
        status=str(AssetStatus.IN_USE),
    )
    session.add(asset)
    session.flush()
    return asset


def get_asset(session: Session, asset_id: int) -> FixedAsset | None:
    return session.get(FixedAsset, asset_id)


def set_depreciation_terms(
    session: Session, asset_id: int, *, useful_life_months: int, salvage_value: Decimal = Decimal("0")
) -> FixedAsset:
    asset = session.get(FixedAsset, asset_id)
    asset.useful_life_months = useful_life_months
    asset.salvage_value = Decimal(str(salvage_value)).quantize(_CENTS)
    session.flush()
    return asset


# ---- depreciation (straight-line) ---------------------------------------

def _monthly_amount(asset: FixedAsset) -> Decimal:
    base = Decimal(str(asset.acquisition_cost)) - Decimal(str(asset.salvage_value))
    if asset.useful_life_months <= 0 or base <= 0:
        return Decimal("0")
    return (base / asset.useful_life_months).quantize(_CENTS)


def run_depreciation(
    session: Session, *, period: str, asset_id: int | None = None
) -> list[DepreciationEntry]:
    """Post one month of straight-line depreciation. Idempotent per (asset, period);
    stops at (cost - salvage)."""
    if asset_id is not None:
        assets = [session.get(FixedAsset, asset_id)]
    else:
        assets = list(session.scalars(select(FixedAsset).where(FixedAsset.status == str(AssetStatus.IN_USE))))

    entry_date = _period_date(period)
    out: list[DepreciationEntry] = []
    for asset in assets:
        if asset is None or asset.status != AssetStatus.IN_USE:
            continue
        already = session.scalar(
            select(DepreciationEntry).where(
                DepreciationEntry.asset_id == asset.id, DepreciationEntry.period == period
            )
        )
        if already is not None:
            continue
        base = Decimal(str(asset.acquisition_cost)) - Decimal(str(asset.salvage_value))
        remaining = base - Decimal(str(asset.accumulated_depreciation))
        if remaining <= 0:
            continue
        amount = min(_monthly_amount(asset), remaining)
        if amount <= 0:
            continue

        entry = DepreciationEntry(asset_id=asset.id, period=period, amount=amount)
        session.add(entry)
        session.flush()
        asset.accumulated_depreciation = (
            Decimal(str(asset.accumulated_depreciation)) + amount
        ).quantize(_CENTS)
        bus.emit(
            DepreciationPosted(depreciation_entry_id=entry.id, entry_date=entry_date, amount=amount),
            session,
        )
        out.append(entry)
    return out


# ---- reclassification (inventory <-> asset) -----------------------------

def reclassify_inventory_to_asset(
    session: Session,
    *,
    product_id: int,
    qty: Decimal = Decimal("1"),
    name: str | None = None,
    useful_life_months: int = 60,
    salvage_value: Decimal = Decimal("0"),
    reclass_date: date | None = None,
    memo: str | None = None,
) -> Reclassification:
    """Move a for-sale item into own-use fixed assets at moving-average cost.
    Dr Fixed Asset / Cr Inventory (accounting books it via the event)."""
    rdate = reclass_date or date.today()
    unit_cost = inv.adjust_out(session, product_id, qty, ref_type="reclass")
    amount = (Decimal(str(qty)) * unit_cost).quantize(_CENTS)

    product = inv.get_product(session, product_id)
    asset = create_asset(
        session,
        name=name or product.name,
        acquisition_cost=amount,
        acquisition_date=rdate,
        product_id=product_id,
        model_name=product.model_name,
        useful_life_months=useful_life_months,
        salvage_value=salvage_value,
    )
    reclass = Reclassification(
        reclass_no=next_number(session, "RCL", _now_year()),
        type=str(ReclassType.INVENTORY_TO_ASSET),
        reclass_date=rdate,
        product_id=product_id,
        qty=Decimal(str(qty)),
        fixed_asset_id=asset.id,
        amount=amount,
        memo=memo,
    )
    session.add(reclass)
    session.flush()
    bus.emit(
        Reclassified(
            reclass_id=reclass.id, type=str(ReclassType.INVENTORY_TO_ASSET),
            entry_date=rdate, amount=amount,
        ),
        session,
    )
    return reclass


def reclassify_asset_to_inventory(
    session: Session,
    *,
    asset_id: int,
    product_id: int,
    reclass_date: date | None = None,
    memo: str | None = None,
) -> Reclassification:
    """Move a used asset into for-sale inventory at net book value (NBV).
    Dr Inventory (NBV) + Dr Accum Deprec / Cr Fixed Asset (cost)."""
    rdate = reclass_date or date.today()
    asset = session.get(FixedAsset, asset_id)
    if asset is None or asset.status != AssetStatus.IN_USE:
        raise ValueError("asset not available for reclassification")

    cost = Decimal(str(asset.acquisition_cost))
    accum = Decimal(str(asset.accumulated_depreciation))
    nbv = (cost - accum).quantize(_CENTS)

    inv.adjust_in(session, product_id, Decimal("1"), nbv, ref_type="reclass")
    asset.status = str(AssetStatus.DISPOSED)

    reclass = Reclassification(
        reclass_no=next_number(session, "RCL", _now_year()),
        type=str(ReclassType.ASSET_TO_INVENTORY),
        reclass_date=rdate,
        product_id=product_id,
        qty=Decimal("1"),
        fixed_asset_id=asset.id,
        amount=nbv,
        accum_depreciation=accum,
        memo=memo,
    )
    session.add(reclass)
    session.flush()
    bus.emit(
        Reclassified(
            reclass_id=reclass.id, type=str(ReclassType.ASSET_TO_INVENTORY),
            entry_date=rdate, amount=nbv, accum_depreciation=accum, acquisition_cost=cost,
        ),
        session,
    )
    return reclass
