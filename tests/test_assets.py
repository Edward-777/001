"""M8 — fixed assets: creation from inbound (no double-post), straight-line
depreciation, and inventory<->asset reclassification with exact accounting."""
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
from app.modules.assets import service as asset_svc
from app.modules.assets.handlers import register_handlers as register_assets
from app.modules.assets.models import AssetStatus
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType

JAN = date(2026, 1, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        register_accounting()
        register_assets()
        s.flush()
        yield s


def _role(session, role):
    return acct.get_account_by_role(session, role).id


def _jes(session):
    return list(session.scalars(select(JournalEntry)))


def _lines(session, je):
    rows = session.scalars(select(JournalLine).where(JournalLine.je_id == je.id)).all()
    return {ln.account_id: (ln.debit, ln.credit) for ln in rows}


# ---- asset created from inbound, booked once --------------------------------

def test_asset_inbound_creates_record_without_double_posting(session):
    laptop = inv.create_product(session, sku="LAP", name="Laptop", type=ProductType.ASSET,
                                model_name="X1")
    session.flush()
    inb = inv.create_inbound(session, received_date=JAN,
                             lines=[{"product_id": laptop.id, "qty": 1, "unit_cost": 1200}])
    inv.post_inbound(session, inb.id)

    # exactly ONE JE (from accounting), and ONE FixedAsset (from assets)
    assert len(_jes(session)) == 1
    asset = session.scalars(select(asset_svc.FixedAsset)).one()
    assert asset.acquisition_cost == Decimal("1200.00")
    assert asset.model_name == "X1"
    assert asset.status == AssetStatus.IN_USE


# ---- depreciation -----------------------------------------------------------

def test_straight_line_depreciation_posts_je(session):
    asset = asset_svc.create_asset(session, name="Laptop",
                                   acquisition_cost=Decimal("1200"), acquisition_date=JAN,
                                   useful_life_months=12, salvage_value=Decimal("0"))
    session.flush()
    asset_svc.run_depreciation(session, period="2026-01")  # 1200/12 = 100

    assert asset.accumulated_depreciation == Decimal("100.00")
    je = [j for j in _jes(session) if j.source_type == "depreciation"][0]
    by = _lines(session, je)
    assert by[_role(session, "deprec_expense")] == (Decimal("100.00"), Decimal("0.00"))
    assert by[_role(session, "accum_deprec")] == (Decimal("0.00"), Decimal("100.00"))


def test_depreciation_idempotent_per_period_and_caps(session):
    asset = asset_svc.create_asset(session, name="A", acquisition_cost=Decimal("100"),
                                   acquisition_date=JAN, useful_life_months=2)
    session.flush()
    asset_svc.run_depreciation(session, period="2026-01")  # 50
    asset_svc.run_depreciation(session, period="2026-01")  # same period -> no-op
    assert asset.accumulated_depreciation == Decimal("50.00")
    asset_svc.run_depreciation(session, period="2026-02")  # 50 -> fully depreciated
    asset_svc.run_depreciation(session, period="2026-03")  # nothing left
    assert asset.accumulated_depreciation == Decimal("100.00")


# ---- reclassification -------------------------------------------------------

def test_inventory_to_asset(session):
    w = inv.create_product(session, sku="W", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, received_date=JAN,
                             lines=[{"product_id": w.id, "qty": 5, "unit_cost": 200}])
    inv.post_inbound(session, inb.id)  # stock 5 @ 200

    asset_svc.reclassify_inventory_to_asset(session, product_id=w.id, qty=Decimal("1"),
                                            reclass_date=JAN)
    # stock down to 4
    assert inv.get_stock(session, w.id).qty_on_hand == 4
    # JE: Dr Fixed Asset 200 / Cr Inventory 200
    je = [j for j in _jes(session) if j.source_type == "reclass"][0]
    by = _lines(session, je)
    assert by[_role(session, "fixed_asset")] == (Decimal("200.00"), Decimal("0.00"))
    assert by[_role(session, "inventory")] == (Decimal("0.00"), Decimal("200.00"))


def test_asset_to_inventory_at_nbv(session):
    # build an asset with cost 1200, depreciate 100 -> NBV 1100
    asset = asset_svc.create_asset(session, name="Laptop", acquisition_cost=Decimal("1200"),
                                   acquisition_date=JAN, useful_life_months=12)
    session.flush()
    asset_svc.run_depreciation(session, period="2026-01")  # accum 100
    resale = inv.create_product(session, sku="LAP-USED", name="Used Laptop",
                                type=ProductType.INVENTORY)
    session.flush()

    asset_svc.reclassify_asset_to_inventory(session, asset_id=asset.id, product_id=resale.id,
                                            reclass_date=date(2026, 2, 1))
    assert asset.status == AssetStatus.DISPOSED
    # stock in at NBV 1100
    bal = inv.get_stock(session, resale.id)
    assert bal.qty_on_hand == 1
    assert bal.avg_unit_cost == Decimal("1100.00")
    # JE: Dr Inventory 1100 + Dr Accum Deprec 100 / Cr Fixed Asset 1200 (balanced)
    je = [j for j in _jes(session) if j.source_type == "reclass" and j.description.endswith("inventory")][0]
    by = _lines(session, je)
    assert by[_role(session, "inventory")] == (Decimal("1100.00"), Decimal("0.00"))
    assert by[_role(session, "accum_deprec")] == (Decimal("100.00"), Decimal("0.00"))
    assert by[_role(session, "fixed_asset")] == (Decimal("0.00"), Decimal("1200.00"))
