"""sales.fulfillment — the order-to-cash pipeline (docs/AGENT-FLEET.md §1, O2C).

Quote -> (send) -> accept with customer PO -> sales order -> ship (packing list,
issues stock) -> invoice. Descriptions/prices flow from the quote through the
whole chain so the packing list and invoice match what was quoted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.money import CENTS as _CENTS
from ...core.money import current_year as _year
from ...core.sequences import next_number
from ..inventory import service as inv
from . import service as sales
from .models import (
    Quote,
    QuoteLine,
    QuoteStatus,
    SalesOrder,
    Shipment,
    ShipmentLine,
    SOStatus,
)


def create_quote(session: Session, *, customer_id: int, lines: list[dict],
                 valid_until: date | None = None, tax_rate: Decimal | float = 0) -> Quote:
    """lines: [{description, qty, unit_price, product_id?}]."""
    q = Quote(quote_no=next_number(session, "QUO", _year()), customer_id=customer_id,
              quote_date=date.today(), valid_until=valid_until, status=str(QuoteStatus.DRAFT))
    session.add(q)
    session.flush()
    subtotal = Decimal("0")
    for ln in lines:
        qty = Decimal(str(ln.get("qty", 1)))
        price = Decimal(str(ln.get("unit_price", 0)))
        amt = (qty * price).quantize(_CENTS)
        subtotal += amt
        session.add(QuoteLine(quote_id=q.id, product_id=ln.get("product_id"),
                              description=ln.get("description"), qty=qty,
                              unit_price=price, amount=amt))
    tax = (subtotal * Decimal(str(tax_rate)) / Decimal("100")).quantize(_CENTS)
    q.subtotal, q.tax_amount, q.total = subtotal, tax, (subtotal + tax).quantize(_CENTS)
    session.flush()
    return q


def send_quote(session: Session, quote_id: int) -> Quote:
    q = session.get(Quote, quote_id)
    if q is None:
        raise ValueError("quote not found")
    q.status = str(QuoteStatus.SENT)
    session.flush()
    return q


def accept_quote(session: Session, quote_id: int, *, customer_po: str) -> SalesOrder:
    """Customer sent a PO -> convert the quote into a sales order."""
    q = session.get(Quote, quote_id)
    if q is None:
        raise ValueError("quote not found")
    so = sales.create_so(session, customer_id=q.customer_id, lines=[
        {"product_id": ln.product_id, "qty": ln.qty, "unit_price": ln.unit_price}
        for ln in q.lines
    ])
    q.status = str(QuoteStatus.ACCEPTED)
    q.customer_po = customer_po
    q.so_id = so.id
    session.flush()
    return so


def _quote_for_so(session: Session, so_id: int) -> Quote | None:
    return session.scalar(select(Quote).where(Quote.so_id == so_id))


def create_shipment(session: Session, *, so_id: int, carrier: str | None = None,
                    tracking_no: str | None = None) -> Shipment:
    """Ship everything on the order (packing list). Issues stock for any product
    line that has enough on hand; service / non-stock lines just ship."""
    so = session.get(SalesOrder, so_id)
    if so is None:
        raise ValueError("sales order not found")
    sh = Shipment(shipment_no=next_number(session, "SHP", _year()), so_id=so.id,
                  customer_id=so.customer_id, ship_date=date.today(),
                  carrier=carrier, tracking_no=tracking_no)
    session.add(sh)
    session.flush()

    quote = _quote_for_so(session, so_id)
    items = ([{"product_id": ln.product_id, "description": ln.description, "qty": ln.qty}
              for ln in quote.lines] if quote else
             [{"product_id": ln.product_id, "description": f"Item (qty {ln.qty_ordered})",
               "qty": ln.qty_ordered} for ln in so.lines])
    for it in items:
        qty = Decimal(str(it["qty"]))
        if qty <= 0:
            continue
        session.add(ShipmentLine(shipment_id=sh.id, product_id=it.get("product_id"),
                                 description=it.get("description"), qty=qty))
        if it.get("product_id") is not None:
            try:
                inv.adjust_out(session, it["product_id"], qty, ref_type="shipment", ref_id=sh.id)
            except ValueError:
                pass  # service / no-stock item — ship without inventory costing

    for ln in so.lines:
        ln.qty_shipped = ln.qty_ordered
    so.status = str(SOStatus.SHIPPED)
    session.flush()
    return sh


def invoice_order(session: Session, so_id: int, *, tax_rate: Decimal | float = 0):
    """Invoice a shipped order — lines mirror the quote so the invoice matches."""
    so = session.get(SalesOrder, so_id)
    if so is None:
        raise ValueError("sales order not found")
    quote = _quote_for_so(session, so_id)
    lines = ([{"description": ln.description, "qty": ln.qty, "unit_price": ln.unit_price,
               "product_id": ln.product_id} for ln in quote.lines] if quote else
             [{"description": "Item", "qty": ln.qty_ordered, "unit_price": ln.unit_price,
               "product_id": ln.product_id} for ln in so.lines])
    invoice = sales.post_ar_invoice(session, customer_id=so.customer_id, lines=lines,
                                    so_id=so_id, tax_rate=tax_rate)
    so.status = str(SOStatus.INVOICED)
    session.flush()
    return invoice


# ---- queries (for the pipeline UI) --------------------------------------

def list_quotes(session: Session) -> list[Quote]:
    return list(session.scalars(select(Quote).order_by(Quote.id.desc())))


def get_quote(session: Session, quote_id: int) -> Quote | None:
    return session.get(Quote, quote_id)


def get_shipment(session: Session, shipment_id: int) -> Shipment | None:
    return session.get(Shipment, shipment_id)
