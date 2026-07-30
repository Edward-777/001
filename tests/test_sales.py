"""M9 — outbound goods issue (COGS/consumption/disposal) and the AR cycle
(invoice = revenue + sales tax, receipt = cash). Sell-side accounting."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.accounting.handlers import register_handlers as register_accounting
from app.modules.accounting.ledger_models import JournalEntry, JournalLine
from app.modules.inventory import service as inv
from app.modules.inventory.models import OutboundType, ProductType
from app.modules.sales import service as sls
from app.modules.sales.models import ARStatus

JAN = date(2026, 1, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        register_accounting()
        s.flush()
        yield s


def _role(session, role):
    return acct.get_account_by_role(session, role).id


def _by_source(session, source_type):
    je = [j for j in session.scalars(select(JournalEntry)) if j.source_type == source_type][0]
    rows = session.scalars(select(JournalLine).where(JournalLine.je_id == je.id)).all()
    return {ln.account_id: (ln.debit, ln.credit) for ln in rows}


def _stocked_product(session, *, qty=10, cost=5):
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, received_date=JAN,
                             lines=[{"product_id": p.id, "qty": qty, "unit_cost": cost}])
    inv.post_inbound(session, inb.id)
    return p


# ---- outbound ----------------------------------------------------------

def test_sale_outbound_books_cogs(session):
    p = _stocked_product(session, qty=10, cost=5)
    ob = inv.create_outbound(session, type=OutboundType.SALE, issue_date=JAN,
                             lines=[{"product_id": p.id, "qty": 4}])
    inv.post_outbound(session, ob.id)

    assert inv.get_stock(session, p.id).qty_on_hand == 6
    by = _by_source(session, "outbound")
    # Dr COGS 20 / Cr Inventory 20  (4 @ 5)
    assert by[_role(session, "cogs")] == (Decimal("20.00"), Decimal("0.00"))
    assert by[_role(session, "inventory")] == (Decimal("0.00"), Decimal("20.00"))


def test_disposal_books_shrinkage(session):
    p = _stocked_product(session, qty=10, cost=5)
    ob = inv.create_outbound(session, type=OutboundType.DISPOSAL, issue_date=JAN,
                             lines=[{"product_id": p.id, "qty": 2}])
    inv.post_outbound(session, ob.id)
    by = _by_source(session, "outbound")
    assert by[_role(session, "inventory_loss")] == (Decimal("10.00"), Decimal("0.00"))
    assert by[_role(session, "inventory")] == (Decimal("0.00"), Decimal("10.00"))


def test_consumption_books_expense(session):
    p = _stocked_product(session, qty=10, cost=5)
    ob = inv.create_outbound(session, type=OutboundType.CONSUMPTION, issue_date=JAN,
                             lines=[{"product_id": p.id, "qty": 3}])
    inv.post_outbound(session, ob.id)
    by = _by_source(session, "outbound")
    # no product-specific expense account -> falls back to supplies_expense
    assert by[_role(session, "supplies_expense")] == (Decimal("15.00"), Decimal("0.00"))
    assert by[_role(session, "inventory")] == (Decimal("0.00"), Decimal("15.00"))


def test_insufficient_stock_rejected(session):
    p = _stocked_product(session, qty=2, cost=5)
    ob = inv.create_outbound(session, type=OutboundType.SALE,
                             lines=[{"product_id": p.id, "qty": 5}])
    with pytest.raises(ValueError, match="insufficient"):
        inv.post_outbound(session, ob.id)


# ---- AR invoice + receipt ----------------------------------------------

def test_ar_invoice_books_revenue_and_tax(session):
    c = sls.create_customer(session, name="Beta Corp")
    session.flush()
    inv_doc = sls.post_ar_invoice(
        session, customer_id=c.id, invoice_date=JAN, tax_rate=10,
        lines=[{"description": "widget", "qty": 10, "unit_price": 10}],  # subtotal 100, tax 10
    )
    assert inv_doc.subtotal == 100 and inv_doc.tax_amount == 10 and inv_doc.total == 110
    by = _by_source(session, "ar_invoice")
    assert by[_role(session, "ar")] == (Decimal("110.00"), Decimal("0.00"))
    assert by[_role(session, "revenue")] == (Decimal("0.00"), Decimal("100.00"))
    assert by[_role(session, "sales_tax")] == (Decimal("0.00"), Decimal("10.00"))


def test_receipt_books_cash_and_settles_invoice(session):
    c = sls.create_customer(session, name="Beta Corp")
    session.flush()
    inv_doc = sls.post_ar_invoice(session, customer_id=c.id, invoice_date=JAN,
                                  lines=[{"description": "x", "qty": 1, "unit_price": 100}])
    # partial receipt 60
    sls.post_receipt(session, customer_id=c.id, receipt_date=JAN,
                     applications=[{"ar_invoice_id": inv_doc.id, "amount": 60}])
    assert inv_doc.balance == 40
    assert inv_doc.status == ARStatus.PARTIALLY_PAID
    by = _by_source(session, "receipt")
    assert by[_role(session, "cash")] == (Decimal("60.00"), Decimal("0.00"))
    assert by[_role(session, "ar")] == (Decimal("0.00"), Decimal("60.00"))

    # pay the rest
    sls.post_receipt(session, customer_id=c.id, receipt_date=JAN,
                     applications=[{"ar_invoice_id": inv_doc.id, "amount": 40}])
    assert inv_doc.balance == 0
    assert inv_doc.status == ARStatus.PAID


def test_full_sale_cycle_cogs_and_revenue(session):
    """Ship (COGS) + invoice (revenue) — both sides of one sale."""
    p = _stocked_product(session, qty=10, cost=5)
    c = sls.create_customer(session, name="Beta")
    session.flush()

    ob = inv.create_outbound(session, type=OutboundType.SALE, issue_date=JAN,
                             lines=[{"product_id": p.id, "qty": 4}])
    inv.post_outbound(session, ob.id)            # Dr COGS 20 / Cr Inventory 20
    sls.post_ar_invoice(session, customer_id=c.id, invoice_date=JAN,
                        lines=[{"product_id": p.id, "qty": 4, "unit_price": 12}])  # revenue 48

    cogs = _by_source(session, "outbound")[_role(session, "cogs")][0]
    rev = _by_source(session, "ar_invoice")[_role(session, "revenue")][1]
    assert cogs == Decimal("20.00")   # cost
    assert rev == Decimal("48.00")    # revenue -> gross margin 28
