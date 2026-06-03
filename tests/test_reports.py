"""M13 — financial reports from the ledger. Builds a real month of activity and
checks the trial balance, P&L, balance sheet, aging, and the 'January close'."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import accounting, inventory, procurement, sales  # noqa: F401
from app.modules.accounting import service as acct
from app.modules.accounting.handlers import register_handlers as register_accounting
from app.modules.inventory import service as inv
from app.modules.inventory.models import OutboundType, ProductType
from app.modules.procurement import service as proc
from app.modules.sales import service as sls

JAN = date(2026, 1, 15)
JAN_END = date(2026, 1, 31)


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


@pytest.fixture
def month(session):
    """Receive 10@10, bill+match (clears GR/IR), sell 4 (COGS 40), invoice 4@25 (rev 100)."""
    vendor = proc.create_vendor(session, name="Acme")
    cust = sls.create_customer(session, name="Beta")
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()

    inb = inv.create_inbound(session, received_date=JAN,
                             lines=[{"product_id": p.id, "qty": 10, "unit_cost": 10}])
    inv.post_inbound(session, inb.id)                     # Dr Inventory 100 / Cr GR-IR 100
    bill = acct.create_ap_bill(session, vendor_id=vendor.id, bill_date=JAN, due_date=date(2026, 1, 10),
                               lines=[{"qty": 10, "unit_price": 10, "inbound_line_id": inb.lines[0].id}])
    acct.match_ap_bill(session, bill.id)                  # Dr GR-IR 100 / Cr AP 100

    ob = inv.create_outbound(session, type=OutboundType.SALE, issue_date=JAN,
                             lines=[{"product_id": p.id, "qty": 4}])
    inv.post_outbound(session, ob.id)                     # Dr COGS 40 / Cr Inventory 40
    sls.post_ar_invoice(session, customer_id=cust.id, invoice_date=JAN, due_date=date(2026, 1, 10),
                        lines=[{"product_id": p.id, "qty": 4, "unit_price": 25}])  # Dr AR 100 / Cr Rev 100
    return dict(product=p, vendor=vendor, customer=cust)


def test_trial_balance_balances(session, month):
    tb = acct.trial_balance(session, as_of=JAN_END)
    assert tb["balanced"]
    assert tb["total_debit"] == Decimal("200.00")   # Inventory 60 + COGS 40 + AR 100
    assert tb["total_credit"] == Decimal("200.00")  # AP 100 + Revenue 100


def test_income_statement(session, month):
    is_ = acct.income_statement(session, start=date(2026, 1, 1), end=JAN_END)
    assert is_["total_revenue"] == Decimal("100.00")
    assert is_["total_expenses"] == Decimal("40.00")  # COGS
    assert is_["net_income"] == Decimal("60.00")


def test_balance_sheet_balances(session, month):
    bs = acct.balance_sheet(session, as_of=JAN_END)
    assert bs["total_assets"] == Decimal("160.00")        # Inventory 60 + AR 100
    assert bs["total_liabilities"] == Decimal("100.00")   # AP
    assert bs["net_income"] == Decimal("60.00")
    assert bs["total_equity"] == Decimal("60.00")
    assert bs["balanced"]


def test_generate_financials_january_close(session, month):
    """The 'give me the January close' request."""
    fin = acct.generate_financials(session, "2026-01")
    assert fin["period"] == "2026-01"
    assert fin["income_statement"]["net_income"] == Decimal("60.00")
    assert fin["balance_sheet"]["balanced"]


def test_gr_ir_cleared_not_in_trial_balance(session, month):
    """GR/IR netted to zero after match -> should not appear in the TB."""
    tb = acct.trial_balance(session, as_of=JAN_END)
    codes = {r["code"] for r in tb["rows"]}
    assert "2050" not in codes  # GR/IR Clearing


def test_inventory_valuation(session, month):
    val = acct.inventory_valuation(session)
    assert val["total_value"] == Decimal("60.00")  # 6 @ 10


def test_ap_and_ar_aging_buckets(session, month):
    # due 2026-01-10, as_of 2026-03-01 -> 50 days past due -> "31-60"
    as_of = date(2026, 3, 1)
    ap = acct.ap_aging(session, as_of=as_of)
    ar = acct.ar_aging(session, as_of=as_of)
    assert ap["total"] == Decimal("100.00")
    assert ap["buckets"]["31-60"] == Decimal("100.00")
    assert ar["total"] == Decimal("100.00")
    assert ar["buckets"]["31-60"] == Decimal("100.00")


def test_period_isolation_in_income_statement(session, month):
    """February has no activity -> zero P&L."""
    is_feb = acct.income_statement(session, start=date(2026, 2, 1), end=date(2026, 2, 28))
    assert is_feb["net_income"] == Decimal("0.00")


def test_subledger_ties_to_gl_control_accounts(session, month):
    """AP/AR/Inventory subledgers must equal their GL control accounts (P0-4)."""
    chk = acct.subledger_check(session, as_of=JAN_END)
    assert chk["all_ok"], chk
    by = {c["control"]: c for c in chk["checks"]}
    assert by["AP"]["gl"] == by["AP"]["subledger"] == Decimal("100.00")
    assert by["AR"]["gl"] == by["AR"]["subledger"] == Decimal("100.00")
    assert by["Inventory"]["gl"] == by["Inventory"]["subledger"] == Decimal("60.00")
