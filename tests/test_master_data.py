"""M3 — master data + Chart of Accounts seed."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc
from app.modules.sales import service as sls

# Every role the M4 posting engine will need (ARCHITECTURE §4).
REQUIRED_ROLES = {
    "cash", "ar", "inventory", "fixed_asset", "accum_deprec",
    "ap", "gr_ir", "sales_tax", "employee_payable",
    "revenue", "cogs", "inventory_loss", "deprec_expense", "bank_fees",
}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_coa_seed_loads(session):
    n = acct.seed_coa(session)
    assert n == 24  # full default chart
    assert acct.get_account_by_code(session, "1300").name == "Inventory Asset"


def test_coa_seed_is_idempotent(session):
    assert acct.seed_coa(session) == 24
    assert acct.seed_coa(session) == 0  # second run inserts nothing


def test_every_posting_role_present(session):
    """The posting engine (M4) must be able to resolve each role to an account."""
    acct.seed_coa(session)
    for role in REQUIRED_ROLES:
        a = acct.get_account_by_role(session, role)
        assert a is not None, f"missing system_role: {role}"


def test_vendor_customer_product_crud(session):
    v = proc.create_vendor(session, name="Acme Supplies", is_1099=True)
    assert proc.get_vendor(session, v.id).name == "Acme Supplies"

    c = sls.create_customer(session, name="Beta Corp")
    assert sls.get_customer(session, c.id).name == "Beta Corp"

    p = inv.create_product(session, sku="WIDGET-1", name="Widget", type=ProductType.INVENTORY)
    assert inv.get_product_by_sku(session, "WIDGET-1").id == p.id


def test_product_type_drives_classification(session):
    laptop_sale = inv.create_product(
        session, sku="LAP-1", name="Laptop", type=ProductType.INVENTORY, track_serial=True
    )
    laptop_asset = inv.create_product(
        session, sku="LAP-2", name="Laptop (own use)", type=ProductType.ASSET
    )
    assert laptop_sale.type == ProductType.INVENTORY
    assert laptop_asset.type == ProductType.ASSET
    assert laptop_sale.track_serial is True
