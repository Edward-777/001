"""Order-to-cash pipeline: quote -> send -> accept(PO) -> ship -> invoice
(docs/AGENT-FLEET.md §1)."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.sales import fulfillment as ful
from app.modules.sales import service as sls
from app.modules.sales.models import QuoteStatus, SOStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _customer(session):
    return sls.create_customer(session, name="BigCo Inc")


def test_full_pipeline_service_lines(session):
    c = _customer(session)
    quote = ful.create_quote(session, customer_id=c.id, lines=[
        {"description": "Widget Pro", "qty": 10, "unit_price": 1500},
        {"description": "Setup fee", "qty": 1, "unit_price": 2000},
    ])
    assert quote.status == QuoteStatus.DRAFT
    assert str(quote.total) == "17000.00"   # 10*1500 + 2000

    ful.send_quote(session, quote.id)
    assert quote.status == QuoteStatus.SENT

    so = ful.accept_quote(session, quote.id, customer_po="PO-99821")
    assert quote.status == QuoteStatus.ACCEPTED
    assert quote.customer_po == "PO-99821"
    assert quote.so_id == so.id
    assert len(so.lines) == 2

    sh = ful.create_shipment(session, so_id=so.id, carrier="FedEx", tracking_no="FX123")
    assert so.status == SOStatus.SHIPPED
    # packing list mirrors the quote
    descs = {ln.description for ln in sh.lines}
    assert descs == {"Widget Pro", "Setup fee"}
    assert all(ln.qty_shipped == ln.qty_ordered for ln in so.lines)

    invoice = ful.invoice_order(session, so.id)
    assert so.status == SOStatus.INVOICED
    assert str(invoice.total) == "17000.00"
    assert invoice.so_id == so.id
    assert len(invoice.lines) == 2


def test_shipment_issues_stock_for_products(session):
    c = _customer(session)
    p = inv.create_product(session, sku="WIDGET-1", name="Widget", type=ProductType.INVENTORY)
    inv.adjust_in(session, p.id, Decimal("100"), Decimal("800"), ref_type="seed")
    assert inv.get_stock(session, p.id).qty_on_hand == 100

    quote = ful.create_quote(session, customer_id=c.id, lines=[
        {"description": "Widget", "qty": 30, "unit_price": 1500, "product_id": p.id}])
    so = ful.accept_quote(session, quote.id, customer_po="PO-1")
    ful.create_shipment(session, so_id=so.id)

    assert inv.get_stock(session, p.id).qty_on_hand == 70  # 100 - 30 shipped


def test_quote_total_with_tax(session):
    c = _customer(session)
    quote = ful.create_quote(session, customer_id=c.id,
                             lines=[{"description": "X", "qty": 1, "unit_price": 1000}],
                             tax_rate=10)
    assert str(quote.subtotal) == "1000.00"
    assert str(quote.tax_amount) == "100.00"
    assert str(quote.total) == "1100.00"
