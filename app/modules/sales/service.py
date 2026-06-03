"""sales.service — customers (M3) + sales orders, AR invoices, receipts (M9).

Revenue is recognized on the AR invoice (Dr AR / Cr Revenue + Cr Sales Tax);
COGS is booked separately on the goods issue (inventory outbound, type=sale).
Cash is booked on receipt (Dr Cash / Cr AR). accounting reacts to the events."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.events import bus
from ...core.sequences import next_number
from .events import ARInvoicePosted, ReceiptPosted
from .models import (
    ARInvoice,
    ARInvoiceLine,
    ARStatus,
    Customer,
    Receipt,
    ReceiptApplication,
    SalesOrder,
    SOLine,
    SOStatus,
)

_CENTS = Decimal("0.01")


def _year() -> int:
    return datetime.now(timezone.utc).year


def create_customer(
    session: Session,
    *,
    name: str,
    customer_no: str | None = None,
    payment_terms: str | None = None,
) -> Customer:
    c = Customer(name=name, customer_no=customer_no, payment_terms=payment_terms)
    session.add(c)
    session.flush()
    return c


def get_customer(session: Session, customer_id: int) -> Customer | None:
    return session.get(Customer, customer_id)


def list_customers(session: Session, *, active_only: bool = True) -> list[Customer]:
    stmt = select(Customer)
    if active_only:
        stmt = stmt.where(Customer.is_active.is_(True))
    return list(session.scalars(stmt))


# ---- sales orders -------------------------------------------------------

def create_so(
    session: Session, *, customer_id: int, order_date: date | None = None, lines: list[dict]
) -> SalesOrder:
    so = SalesOrder(
        so_no=next_number(session, "SO", _year()),
        customer_id=customer_id,
        order_date=order_date or date.today(),
        status=str(SOStatus.OPEN),
    )
    session.add(so)
    session.flush()
    for ln in lines:
        qty = Decimal(str(ln.get("qty", 0)))
        price = Decimal(str(ln.get("unit_price", 0)))
        session.add(
            SOLine(
                so_id=so.id, product_id=ln.get("product_id"),
                qty_ordered=qty, unit_price=price, amount=(qty * price).quantize(_CENTS),
            )
        )
    session.flush()
    return so


# ---- AR invoice (revenue recognition) -----------------------------------

def post_ar_invoice(
    session: Session,
    *,
    customer_id: int,
    lines: list[dict],
    invoice_date: date | None = None,
    due_date: date | None = None,
    tax_rate: Decimal | float = 0,
    so_id: int | None = None,
) -> ARInvoice:
    """lines: [{description, qty, unit_price, product_id?}]. tax_rate is a percent."""
    idate = invoice_date or date.today()
    inv = ARInvoice(
        invoice_no=next_number(session, "INV", _year()),
        customer_id=customer_id,
        so_id=so_id,
        invoice_date=idate,
        due_date=due_date,
        status=str(ARStatus.OPEN),
    )
    session.add(inv)
    session.flush()

    subtotal = Decimal("0")
    for ln in lines:
        qty = Decimal(str(ln.get("qty", 1)))
        price = Decimal(str(ln.get("unit_price", 0)))
        amount = (qty * price).quantize(_CENTS)
        subtotal += amount
        session.add(
            ARInvoiceLine(
                ar_invoice_id=inv.id, product_id=ln.get("product_id"),
                description=ln.get("description"), qty=qty, unit_price=price, amount=amount,
            )
        )
    tax = (subtotal * Decimal(str(tax_rate)) / Decimal("100")).quantize(_CENTS)
    total = (subtotal + tax).quantize(_CENTS)
    inv.subtotal, inv.tax_amount, inv.total, inv.balance = subtotal, tax, total, total
    session.flush()

    bus.emit(
        ARInvoicePosted(invoice_id=inv.id, entry_date=idate, subtotal=subtotal,
                        tax_amount=tax, total=total),
        session,
    )
    return inv


def get_invoice(session: Session, invoice_id: int) -> ARInvoice | None:
    return session.get(ARInvoice, invoice_id)


# ---- receipts (cash collection) -----------------------------------------

def post_receipt(
    session: Session,
    *,
    customer_id: int,
    applications: list[dict],
    receipt_date: date | None = None,
    method: str | None = None,
    bank_account_id: int | None = None,
) -> Receipt:
    """applications: [{ar_invoice_id, amount}] — reduces each invoice balance."""
    rdate = receipt_date or date.today()
    total = sum((Decimal(str(a["amount"])) for a in applications), Decimal("0")).quantize(_CENTS)
    rct = Receipt(
        receipt_no=next_number(session, "RCT", _year()),
        customer_id=customer_id,
        receipt_date=rdate,
        amount=total,
        method=method,
        bank_account_id=bank_account_id,
    )
    session.add(rct)
    session.flush()

    for a in applications:
        amt = Decimal(str(a["amount"]))
        inv = session.get(ARInvoice, a["ar_invoice_id"])
        if inv is None:
            raise ValueError("invoice not found")
        new_balance = (Decimal(str(inv.balance)) - amt).quantize(_CENTS)
        inv.balance = new_balance
        inv.status = str(ARStatus.PAID if new_balance <= 0 else ARStatus.PARTIALLY_PAID)
        session.add(
            ReceiptApplication(receipt_id=rct.id, ar_invoice_id=inv.id, applied_amount=amt)
        )
    session.flush()

    bus.emit(ReceiptPosted(receipt_id=rct.id, entry_date=rdate, amount=total), session)
    return rct
