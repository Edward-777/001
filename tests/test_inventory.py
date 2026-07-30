"""M7 — the architecture-validation milestone.

Inbound posting must, in ONE transaction:
  1. update moving-average stock (inventory items),
  2. emit InboundPosted,
  3. trigger the accounting handler to post a balanced JE
     (Dr Inventory / Fixed Asset, Cr GR-IR), routed by product type.
This proves the event + posting-engine decoupling end to end.
"""
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
from app.modules.inventory.models import ProductType

JAN = date(2026, 1, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        register_accounting()  # opt in: inbound -> JE
        s.flush()
        yield s


def _role_acct(session, role):
    return acct.get_account_by_role(session, role).id


def _je_lines(session):
    je = session.scalars(select(JournalEntry)).one()
    lines = session.scalars(select(JournalLine).where(JournalLine.je_id == je.id)).all()
    return je, {ln.account_id: (ln.debit, ln.credit) for ln in lines}


# ---- moving average -----------------------------------------------------

def test_moving_average_across_two_receipts(session):
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()

    inb1 = inv.create_inbound(session, lines=[{"product_id": p.id, "qty": 10, "unit_cost": 5}])
    inv.post_inbound(session, inb1.id)
    bal = inv.get_stock(session, p.id)
    assert bal.qty_on_hand == 10
    assert bal.avg_unit_cost == Decimal("5.00")

    # receive 10 more @ 7  -> avg = (10*5 + 10*7)/20 = 6.00
    inb2 = inv.create_inbound(session, lines=[{"product_id": p.id, "qty": 10, "unit_cost": 7}])
    inv.post_inbound(session, inb2.id)
    bal = inv.get_stock(session, p.id)
    assert bal.qty_on_hand == 20
    assert bal.avg_unit_cost == Decimal("6.00")
    assert bal.total_value == Decimal("120.00")


# ---- the proof: inbound -> auto-posted journal entry --------------------

def test_inbound_inventory_auto_posts_je(session):
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(
        session, received_date=JAN, lines=[{"product_id": p.id, "qty": 10, "unit_cost": 5}]
    )
    inv.post_inbound(session, inb.id)

    je, by_acct = _je_lines(session)
    assert je.source_type == "inbound"
    assert je.source_id == inb.id
    assert je.entry_date == JAN
    # Dr Inventory 50 / Cr GR-IR 50
    assert by_acct[_role_acct(session, "inventory")] == (Decimal("50.00"), Decimal("0.00"))
    assert by_acct[_role_acct(session, "gr_ir")] == (Decimal("0.00"), Decimal("50.00"))


def test_inbound_asset_routes_to_fixed_asset(session):
    a = inv.create_product(session, sku="LAP", name="Laptop", type=ProductType.ASSET)
    session.flush()
    inb = inv.create_inbound(session, lines=[{"product_id": a.id, "qty": 1, "unit_cost": 1200}])
    inv.post_inbound(session, inb.id)

    _, by_acct = _je_lines(session)
    # Dr Fixed Asset 1200 / Cr GR-IR 1200; asset does NOT touch stock
    assert by_acct[_role_acct(session, "fixed_asset")] == (Decimal("1200.00"), Decimal("0.00"))
    assert by_acct[_role_acct(session, "gr_ir")] == (Decimal("0.00"), Decimal("1200.00"))
    assert inv.get_stock(session, a.id) is None


def test_mixed_inbound_one_balanced_je(session):
    """A single inbound with both an inventory and an asset line -> one JE with
    two debits and one GR-IR credit, balanced."""
    w = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    a = inv.create_product(session, sku="LAP", name="Laptop", type=ProductType.ASSET)
    session.flush()
    inb = inv.create_inbound(
        session,
        lines=[
            {"product_id": w.id, "qty": 10, "unit_cost": 5},   # 50 inventory
            {"product_id": a.id, "qty": 1, "unit_cost": 1200},  # 1200 asset
        ],
    )
    inv.post_inbound(session, inb.id)

    je, by_acct = _je_lines(session)
    assert by_acct[_role_acct(session, "inventory")][0] == Decimal("50.00")
    assert by_acct[_role_acct(session, "fixed_asset")][0] == Decimal("1200.00")
    assert by_acct[_role_acct(session, "gr_ir")][1] == Decimal("1250.00")
    total_dr = sum(d for d, _ in by_acct.values())
    total_cr = sum(c for _, c in by_acct.values())
    assert total_dr == total_cr == Decimal("1250.00")


def test_stock_movement_recorded(session):
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, lines=[{"product_id": p.id, "qty": 3, "unit_cost": 9}])
    inv.post_inbound(session, inb.id)
    from app.modules.inventory.models import StockMovement

    moves = session.scalars(select(StockMovement).where(StockMovement.product_id == p.id)).all()
    assert len(moves) == 1
    assert moves[0].qty == 3
    assert moves[0].movement_type == "inbound"


def test_no_handler_means_no_je_but_stock_still_updates(session):
    """Without the accounting handler, stock still updates (modules are decoupled);
    only the booking is skipped."""
    from app.core.events import bus
    bus.clear()  # drop the accounting subscription for this test
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, lines=[{"product_id": p.id, "qty": 2, "unit_cost": 4}])
    inv.post_inbound(session, inb.id)

    assert inv.get_stock(session, p.id).qty_on_hand == 2
    assert session.scalars(select(JournalEntry)).first() is None
