"""Approval domain events. RequestApproved is what M6 (procurement) listens to
in order to auto-create a Purchase Order for approved purchase requests."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ...core.events import Event


@dataclass
class RequestApproved(Event):
    request_id: int
    request_type: str
    total_amount: Decimal
