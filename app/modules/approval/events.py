"""Approval domain events.

RequestApproved carries a full snapshot (incl. line items) so reactors like
procurement (M6) can act WITHOUT calling back into approval — keeping the
dependency one-way (events down, never up). ARCHITECTURE §3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ...core.events import Event


@dataclass
class RequestApproved(Event):
    request_id: int
    request_type: str
    requester_id: int
    total_amount: Decimal
    # [{product_id, description, qty, unit_price}]
    lines: list[dict] = field(default_factory=list)
