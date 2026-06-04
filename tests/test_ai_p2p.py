"""Phase 2d slice — the AI drives procure-to-pay end to end (receive → bill →
3-way match → pay), with the accounting posted under the hood. Permission-scoped."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import accounting, ai, inventory, procurement  # noqa: F401
from app.modules.accounting import service as acct
from app.modules.accounting.handlers import register_handlers as register_accounting
from app.modules.ai.registry import registry
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def setup(session):
    acct.seed_coa(session)
    acct.seed_posting_rules(session)
    register_accounting()
    v = proc.create_vendor(session, name="Acme Supplies")
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    admin = auth_svc.create_user(session, name="Admin", email="a@x", password="pw", role=Role.ADMIN)
    session.flush()
    return SimpleNamespace(admin=admin, vendor=v, product=p)


def _run(session, user, name, args):
    return registry.execute(name, args, session=session, user=user)["result"]


def test_procure_to_pay_chain(session, setup):
    # 1. receive 100 @ $5  -> stock + Dr Inventory / Cr GR-IR
    r = _run(session, setup.admin, "receive_inventory", {"sku": "W1", "qty": 100, "unit_cost": 5})
    assert float(r["qty_on_hand"]) == 100
    inbound_no = r["inbound_no"]

    # 2. vendor bills that receipt -> 3-way match clears GR/IR to AP
    r = _run(session, setup.admin, "record_vendor_bill",
             {"vendor": "Acme", "against_inbound_no": inbound_no, "invoice_no": "INV-77"})
    assert float(r["amount"]) == 500
    assert r["match_status"] == "matched"
    bill_no = r["bill_no"]

    # 3. pay it -> Dr AP / Cr Cash
    r = _run(session, setup.admin, "pay_vendor", {"bill_no": bill_no})
    assert float(r["paid"]) == 500
    assert r["bill_status"] == "paid"

    # GR/IR nets to zero; AP nets to zero after payment (full procure-to-pay)
    from datetime import date
    chk = acct.subledger_check(session, as_of=date.today())
    ap = next(c for c in chk["checks"] if c["control"] == "AP")
    assert float(ap["subledger"]) == 0


def test_amount_comes_from_receipt_not_fabricated(session, setup):
    """record_vendor_bill ignores any model-supplied amount — it derives from the
    receipt, so the AP figure can never be a hallucinated number."""
    r = _run(session, setup.admin, "receive_inventory", {"sku": "W1", "qty": 10, "unit_cost": 7})
    r = _run(session, setup.admin, "record_vendor_bill",
             {"vendor": "Acme", "against_inbound_no": r["inbound_no"], "amount": 99999})
    assert float(r["amount"]) == 70  # 10 * 7, from the receipt — not 99999


def test_direct_bill_posts_to_chosen_account(session, setup):
    """A vendor bill with no receipt books to the account the user chose
    (here Equipment, since a server is a capital asset) — Dr 1500 / Cr AP 2000."""
    r = _run(session, setup.admin, "record_direct_bill",
             {"vendor": "Acme", "amount": 1000, "account_code": "1500", "description": "Dell server"})
    assert float(r["amount"]) == 1000
    assert "1500" in r["booked_to"]

    from datetime import date
    by = {row["code"]: row for row in acct.trial_balance(session, as_of=date.today())["rows"]}
    assert float(by["1500"]["debit"]) == 1000   # Equipment
    assert float(by["2000"]["credit"]) == 1000  # Accounts Payable


def test_direct_bill_rejects_unknown_account(session, setup):
    r = _run(session, setup.admin, "record_direct_bill",
             {"vendor": "Acme", "amount": 1000, "account_code": "9999"})
    assert "account_code not found" in r["error"]


def test_p2p_tools_require_finance_and_inventory_scopes(session, setup):
    emp = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")  # employee
    names = {t["function"]["name"] for t in registry.schemas_for(emp)}
    assert "record_vendor_bill" not in names    # finance:2 — withheld
    assert "receive_inventory" not in names      # inventory:2 — withheld
    out = registry.execute("pay_vendor", {"bill_no": "X"}, session=session, user=emp)
    assert "permission denied" in out["error"]
