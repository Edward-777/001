"""Asset domain events. accounting reacts to these to post the GL entries
(assets never touches GL accounts — ARCHITECTURE §3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


from ...core.events import Event


@dataclass
class DepreciationPosted(Event):
    depreciation_entry_id: int
    entry_date: date
    amount: Decimal


@dataclass
class Reclassified(Event):
    reclass_id: int
    type: str  # inventory_to_asset | asset_to_inventory
    entry_date: date
    amount: Decimal  # inventory cost (in->asset) or NBV (asset->inv)
    accum_depreciation: Decimal = Decimal("0")  # asset->inv only
    acquisition_cost: Decimal = Decimal("0")  # asset->inv only
