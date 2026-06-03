"""accounting reacts to business events and books journal entries (ARCHITECTURE §3).

This is the decoupling that matters: inventory/procurement know ZERO about GL
accounts — they emit events; accounting owns the account mapping and posts here.
Everything runs in the emitter's transaction (all-or-nothing).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ...core.events import bus
from ..inventory.events import InboundPosted
from .ledger_models import JournalSource
from .posting import Line, post_journal
from .service import get_account_by_role

_CENTS = Decimal("0.01")


def on_inbound_posted(event: InboundPosted, session: Session) -> None:
    """One balanced JE per inbound:
        Dr Inventory      (Σ inventory-line amounts)
        Dr Fixed Asset    (Σ asset-line amounts)
            Cr GR/IR      (total)
    Routed by product_type (SCHEMA inbound classification).
    """
    inv_total = Decimal("0")
    asset_total = Decimal("0")
    for ln in event.lines:
        amount = Decimal(str(ln["amount"]))
        if ln["product_type"] == "inventory":
            inv_total += amount
        elif ln["product_type"] == "asset":
            asset_total += amount

    total = (inv_total + asset_total).quantize(_CENTS)
    if total <= 0:
        return

    lines: list[Line] = []
    if inv_total > 0:
        lines.append(Line(get_account_by_role(session, "inventory").id, debit=inv_total))
    if asset_total > 0:
        lines.append(Line(get_account_by_role(session, "fixed_asset").id, debit=asset_total))
    lines.append(Line(get_account_by_role(session, "gr_ir").id, credit=total))

    post_journal(
        session,
        entry_date=event.entry_date,
        lines=lines,
        description=f"Goods receipt (inbound #{event.inbound_id})",
        source_type=JournalSource.INBOUND,
        source_id=event.inbound_id,
    )


def register_handlers() -> None:
    bus.subscribe(InboundPosted, on_inbound_posted)
