"""accounting reacts to business events and books journal entries (ARCHITECTURE §3).

This is the decoupling that matters: inventory/procurement know ZERO about GL
accounts — they emit events; accounting owns the account mapping and posts here.
Everything runs in the emitter's transaction (all-or-nothing).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ...core.events import bus
from ..assets.events import DepreciationPosted, Reclassified
from ..inventory.events import InboundPosted, OutboundPosted
from ..sales.events import ARInvoicePosted, ReceiptPosted
from .ledger_models import JournalSource
from .posting import Line, apply_rule, post_journal
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


def on_outbound_posted(event: OutboundPosted, session: Session) -> None:
    """Book a goods issue by type:
        sale        -> Dr COGS / Cr Inventory
        disposal    -> Dr Inventory Shrinkage / Cr Inventory
        consumption -> Dr expense(s) / Cr Inventory  (per-product expense account)
    """
    total = sum((Decimal(str(ln["amount"])) for ln in event.lines), Decimal("0")).quantize(_CENTS)
    if total <= 0:
        return

    if event.outbound_type in ("sale", "disposal"):
        apply_rule(
            session,
            event_type="outbound.posted",
            condition=event.outbound_type,
            amount=total,
            entry_date=event.entry_date,
            description=f"Goods issue ({event.outbound_type}) #{event.outbound_id}",
            source_type=JournalSource.OUTBOUND,
            source_id=event.outbound_id,
        )
        return

    # consumption: group debits by expense account (fallback to supplies_expense)
    fallback = get_account_by_role(session, "supplies_expense").id
    by_acct: dict[int, Decimal] = {}
    for ln in event.lines:
        acct = ln.get("expense_account_id") or fallback
        by_acct[acct] = by_acct.get(acct, Decimal("0")) + Decimal(str(ln["amount"]))

    lines = [Line(acct, debit=amt) for acct, amt in by_acct.items()]
    lines.append(Line(get_account_by_role(session, "inventory").id, credit=total))
    post_journal(
        session,
        entry_date=event.entry_date,
        lines=lines,
        description=f"Goods issue (consumption) #{event.outbound_id}",
        source_type=JournalSource.OUTBOUND,
        source_id=event.outbound_id,
    )


def on_depreciation_posted(event: DepreciationPosted, session: Session) -> None:
    """Dr Depreciation Expense / Cr Accumulated Depreciation."""
    apply_rule(
        session,
        event_type="depreciation.run",
        amount=event.amount,
        entry_date=event.entry_date,
        description="Monthly depreciation",
        source_type=JournalSource.DEPRECIATION,
        source_id=event.depreciation_entry_id,
    )


def on_reclassified(event: Reclassified, session: Session) -> None:
    if event.type == "inventory_to_asset":
        # Dr Fixed Asset / Cr Inventory (simple 2-line rule)
        apply_rule(
            session,
            event_type="reclass.posted",
            condition="inv_to_asset",
            amount=event.amount,
            entry_date=event.entry_date,
            description="Reclass inventory -> asset",
            source_type=JournalSource.RECLASS,
            source_id=event.reclass_id,
        )
    else:
        # asset_to_inventory: Dr Inventory (NBV) + Dr Accum Deprec / Cr Fixed Asset (cost)
        lines = [Line(get_account_by_role(session, "inventory").id, debit=event.amount)]
        if event.accum_depreciation > 0:
            lines.append(
                Line(get_account_by_role(session, "accum_deprec").id, debit=event.accum_depreciation)
            )
        lines.append(
            Line(get_account_by_role(session, "fixed_asset").id, credit=event.acquisition_cost)
        )
        post_journal(
            session,
            entry_date=event.entry_date,
            lines=lines,
            description="Reclass asset -> inventory",
            source_type=JournalSource.RECLASS,
            source_id=event.reclass_id,
        )


def on_ar_invoice_posted(event: ARInvoicePosted, session: Session) -> None:
    """Dr Accounts Receivable / Cr Revenue (+ Cr Sales Tax Payable)."""
    lines = [
        Line(get_account_by_role(session, "ar").id, debit=event.total),
        Line(get_account_by_role(session, "revenue").id, credit=event.subtotal),
    ]
    if event.tax_amount > 0:
        lines.append(Line(get_account_by_role(session, "sales_tax").id, credit=event.tax_amount))
    post_journal(
        session,
        entry_date=event.entry_date,
        lines=lines,
        description=f"Customer invoice #{event.invoice_id}",
        source_type=JournalSource.AR_INVOICE,
        source_id=event.invoice_id,
    )


def on_receipt_posted(event: ReceiptPosted, session: Session) -> None:
    """Dr Cash / Cr Accounts Receivable."""
    apply_rule(
        session,
        event_type="receipt.posted",
        amount=event.amount,
        entry_date=event.entry_date,
        description=f"Customer receipt #{event.receipt_id}",
        source_type=JournalSource.RECEIPT,
        source_id=event.receipt_id,
    )


def register_handlers() -> None:
    bus.subscribe(InboundPosted, on_inbound_posted)
    bus.subscribe(OutboundPosted, on_outbound_posted)
    bus.subscribe(DepreciationPosted, on_depreciation_posted)
    bus.subscribe(Reclassified, on_reclassified)
    bus.subscribe(ARInvoicePosted, on_ar_invoice_posted)
    bus.subscribe(ReceiptPosted, on_receipt_posted)
