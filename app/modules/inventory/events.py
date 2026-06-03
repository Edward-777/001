"""Inventory domain events.

InboundPosted carries the receipt date + per-line
{product_id, product_type, qty, unit_cost, amount} so accounting can post the
journal entry and assets (M8) can create FixedAsset records — neither module is
called directly (ARCHITECTURE §3)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ...core.events import Event


@dataclass
class InboundPosted(Event):
    inbound_id: int
    entry_date: date
    lines: list[dict] = field(default_factory=list)


@dataclass
class OutboundPosted(Event):
    outbound_id: int
    entry_date: date
    outbound_type: str  # sale | consumption | disposal | transfer
    # [{product_id, qty, unit_cost, amount, expense_account_id}]
    lines: list[dict] = field(default_factory=list)
