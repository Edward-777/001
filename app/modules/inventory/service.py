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
from .events import InboundPosted, OutboundPosted
from .models import (
    Inbound,
    InboundLine,
    InboundStatus,
    MovementType,
    Outbound,
    OutboundLine,
    OutboundType,
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


def get_inbound_line(session: Session, inbound_line_id: int) -> InboundLine | None:
    """Receipt detail (qty_received, unit_cost) — used by AP 3-way match (M10)."""
    return session.get(InboundLine, inbound_line_id)


def inventory_valuation(session: Session) -> list[StockBalance]:
    """On-hand balances with moving-average value — for the inventory report (M13)."""
    return list(session.scalars(select(StockBalance).where(StockBalance.qty_on_hand != 0)))


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


# ---- generic stock issue/receipt (reused by reclass M8, outbound M9) ------

def adjust_out(
    session: Session, product_id: int, qty: Decimal, *, ref_type: str, ref_id: int | None = None
) -> Decimal:
    """Issue qty from stock at the current moving-average cost. Returns that cost.
    Average is unchanged on issue; only quantity/value drop."""
    bal = get_stock(session, product_id)
    qty = Decimal(str(qty))
    if bal is None or Decimal(str(bal.qty_on_hand)) < qty:
        raise ValueError("insufficient stock")
    unit_cost = Decimal(str(bal.avg_unit_cost))
    new_qty = Decimal(str(bal.qty_on_hand)) - qty
    bal.qty_on_hand = new_qty
    bal.total_value = (new_qty * unit_cost).quantize(_CENTS)
    session.add(
        StockMovement(
            product_id=product_id, movement_type=str(MovementType.OUTBOUND),
            qty=-qty, unit_cost=unit_cost, ref_type=ref_type, ref_id=ref_id,
        )
    )
    return unit_cost


def adjust_in(
    session: Session, product_id: int, qty: Decimal, unit_cost: Decimal,
    *, ref_type: str, ref_id: int | None = None,
) -> None:
    """Receive qty into stock at a given unit cost (blends into moving average)."""
    qty, unit_cost = Decimal(str(qty)), Decimal(str(unit_cost))
    _receive_into_stock(session, product_id, qty, unit_cost)
    session.add(
        StockMovement(
            product_id=product_id, movement_type=str(MovementType.ADJUSTMENT),
            qty=qty, unit_cost=unit_cost, ref_type=ref_type, ref_id=ref_id,
        )
    )


# ---- outbound (goods issue) ---------------------------------------------

def create_outbound(
    session: Session,
    *,
    type: OutboundType = OutboundType.SALE,
    issue_date: date | None = None,
    lines: list[dict],
    ref_type: str | None = None,
    ref_id: int | None = None,
    memo: str | None = None,
) -> Outbound:
    """lines: [{product_id, qty}]. unit_cost is set at posting from moving average."""
    ob = Outbound(
        outbound_no=next_number(session, "OUT", datetime.now(timezone.utc).year),
        type=str(type),
        issue_date=issue_date or date.today(),
        ref_type=ref_type,
        ref_id=ref_id,
        memo=memo,
        status=str(InboundStatus.DRAFT),
    )
    session.add(ob)
    session.flush()
    for ln in lines:
        session.add(
            OutboundLine(
                outbound_id=ob.id, product_id=ln["product_id"], qty=Decimal(str(ln["qty"]))
            )
        )
    session.flush()
    return ob


def post_outbound(session: Session, outbound_id: int) -> Outbound:
    """Issue stock at moving-average cost and emit OutboundPosted (accounting books
    COGS / expense / shrinkage per outbound type)."""
    ob = session.get(Outbound, outbound_id)
    if ob is None or ob.status != InboundStatus.DRAFT:
        raise ValueError("outbound not in draft")
    if ob.type == OutboundType.TRANSFER:
        raise ValueError("transfer (multi-warehouse) not supported in Phase 1")

    snapshot: list[dict] = []
    for line in ob.lines:
        unit_cost = adjust_out(session, line.product_id, Decimal(str(line.qty)),
                               ref_type="outbound", ref_id=ob.id)
        line.unit_cost = unit_cost
        amount = (Decimal(str(line.qty)) * unit_cost).quantize(_CENTS)
        product = session.get(Product, line.product_id)
        snapshot.append(
            {
                "product_id": line.product_id,
                "qty": Decimal(str(line.qty)),
                "unit_cost": unit_cost,
                "amount": amount,
                "expense_account_id": product.default_expense_account_id if product else None,
            }
        )

    ob.status = str(InboundStatus.POSTED)
    session.flush()
    bus.emit(
        OutboundPosted(
            outbound_id=ob.id, entry_date=ob.issue_date,
            outbound_type=str(ob.type), lines=snapshot,
        ),
        session,
    )
    return ob
