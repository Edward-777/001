"""assets reacts to inbound events to create FixedAsset records.

NOTE: accounting already booked Dr Fixed Asset / Cr GR-IR for the same inbound
(its own InboundPosted handler). assets ONLY creates the tracking record here —
no posting, so there's no double entry (ARCHITECTURE §3 division of labor).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ...core.events import bus
from ..inventory import service as inv
from ..inventory.events import InboundPosted
from . import service


def on_inbound_posted(event: InboundPosted, session: Session) -> None:
    for ln in event.lines:
        if ln["product_type"] != "asset":
            continue
        product = inv.get_product(session, ln["product_id"])
        service.create_asset(
            session,
            name=product.name if product else f"Asset (product {ln['product_id']})",
            acquisition_cost=Decimal(str(ln["amount"])),
            acquisition_date=event.entry_date,
            product_id=ln["product_id"],
            model_name=product.model_name if product else None,
        )


def register_handlers() -> None:
    bus.subscribe(InboundPosted, on_inbound_posted)
