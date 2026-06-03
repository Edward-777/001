"""inventory.service — product master (M3) + inbound/stock (M7).

post_inbound updates moving-average stock and emits InboundPosted; accounting
reacts to post the journal entry (Dr Inventory/Fixed Asset, Cr GR-IR)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.events import bus
from ...core.sequences import next_number
from .events import InboundPosted
from .models import (
    Inbound,
    InboundLine,
    InboundStatus,
    MovementType,
    Product,
    ProductCategory,
    ProductType,
    StockBalance,
    StockMovement,
)

_CENTS = Decimal("0.01")


def create_category(
    session: Session, *, name: str, parent_id: int | None = None
) -> ProductCategory:
    cat = ProductCategory(name=name, parent_id=parent_id)
    session.add(cat)
    session.flush()
    return cat


def create_product(
    session: Session,
    *,
    sku: str,
    name: str,
    type: ProductType = ProductType.INVENTORY,
    model_name: str | None = None,
    track_serial: bool = False,
    unit: str = "ea",
    category_id: int | None = None,
    standard_cost: Decimal | float | None = None,
) -> Product:
    p = Product(
        sku=sku,
        name=name,
        type=str(type),
        model_name=model_name,
        track_serial=track_serial,
        unit=unit,
        category_id=category_id,
        standard_cost=Decimal(str(standard_cost)) if standard_cost is not None else None,
    )
    session.add(p)
    session.flush()
    return p


def get_product(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)


def get_product_by_sku(session: Session, sku: str) -> Product | None:
    return session.scalar(select(Product).where(Product.sku == sku))


# ---- stock balances (moving average) ------------------------------------

def get_stock(session: Session, product_id: int) -> StockBalance | None:
    return session.scalar(select(StockBalance).where(StockBalance.product_id == product_id))


def _receive_into_stock(session: Session, product_id: int, qty: Decimal, unit_cost: Decimal) -> None:
    """Apply moving average: new_avg = (old_qty*old_avg + in_qty*in_cost)/new_qty."""
    bal = get_stock(session, product_id)
    if bal is None:
        bal = StockBalance(
            product_id=product_id, qty_on_hand=Decimal("0"),
            avg_unit_cost=Decimal("0"), total_value=Decimal("0"),
        )
        session.add(bal)
        session.flush()

    old_qty = Decimal(str(bal.qty_on_hand))
    old_avg = Decimal(str(bal.avg_unit_cost))
    new_qty = old_qty + qty
    if new_qty > 0:
        new_avg = ((old_qty * old_avg) + (qty * unit_cost)) / new_qty
    else:
        new_avg = Decimal("0")
    bal.qty_on_hand = new_qty
    bal.avg_unit_cost = new_avg.quantize(_CENTS)
    bal.total_value = (new_qty * new_avg).quantize(_CENTS)


# ---- inbound (goods receipt) --------------------------------------------

def create_inbound(
    session: Session,
    *,
    po_id: int | None = None,
    received_date: date | None = None,
    lines: list[dict],
) -> Inbound:
    """lines: [{product_id, qty, unit_cost, po_line_id?}]."""
    inb = Inbound(
        inbound_no=next_number(session, "INB", datetime.now(timezone.utc).year),
        po_id=po_id,
        received_date=received_date or date.today(),
        status=str(InboundStatus.DRAFT),
    )
    session.add(inb)
    session.flush()
    for ln in lines:
        session.add(
            InboundLine(
                inbound_id=inb.id,
                po_line_id=ln.get("po_line_id"),
                product_id=ln["product_id"],
                qty_received=Decimal(str(ln["qty"])),
                unit_cost=Decimal(str(ln["unit_cost"])),
            )
        )
    session.flush()
    return inb


def post_inbound(session: Session, inbound_id: int) -> Inbound:
    """Post a goods receipt: update stock for inventory items, then emit
    InboundPosted so accounting books it (same transaction = all-or-nothing)."""
    inb = session.get(Inbound, inbound_id)
    if inb is None or inb.status != InboundStatus.DRAFT:
        raise ValueError("inbound not in draft")

    snapshot: list[dict] = []
    for line in inb.lines:
        product = session.get(Product, line.product_id)
        ptype = ProductType(product.type)
        qty = Decimal(str(line.qty_received))
        unit_cost = Decimal(str(line.unit_cost))
        amount = (qty * unit_cost).quantize(_CENTS)

        # Only inventory items affect stock; assets become fixed assets (M8).
        if ptype == ProductType.INVENTORY:
            _receive_into_stock(session, product.id, qty, unit_cost)
            session.add(
                StockMovement(
                    product_id=product.id,
                    movement_type=str(MovementType.INBOUND),
                    qty=qty,
                    unit_cost=unit_cost,
                    ref_type="inbound",
                    ref_id=inb.id,
                )
            )
        snapshot.append(
            {
                "product_id": product.id,
                "product_type": str(ptype),
                "qty": qty,
                "unit_cost": unit_cost,
                "amount": amount,
            }
        )

    inb.status = str(InboundStatus.POSTED)
    session.flush()
    bus.emit(
        InboundPosted(inbound_id=inb.id, entry_date=inb.received_date, lines=snapshot),
        session,
    )
    return inb
