"""M10 — AP 3-way match + payment. Closes the buy-side loop: the GR/IR accrued
at goods receipt (M7) is cleared when the vendor bill matches; payment settles AP."""
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
from app.modules.accounting.ap_models import APBillStatus, APMatchStatus
from app.modules.accounting.handlers import register_handlers as register_accounting
from app.modules.accounting.ledger_models import JournalLine
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc

JAN = date(2026, 1, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        register_accounting()  # inbound posts Dr Inventory / Cr GR-IR
        s.flush()
        yield s


def _gr_ir_balance(session) -> Decimal:
    """Net GR/IR = Σcredit - Σdebit on the clearing account (should be 0 once matched)."""
    acc = acct.get_account_by_role(session, "gr_ir").id
    lines = session.scalars(select(JournalLine).where(JournalLine.account_id == acc)).all()
    return sum((Decimal(str(ln.credit)) - Decimal(str(ln.debit)) for ln in lines), Decimal("0"))


def _ap_balance(session) -> Decimal:
    acc = acct.get_account_by_role(session, "ap").id
    lines = session.scalars(select(JournalLine).where(JournalLine.account_id == acc)).all()
    return sum((Decimal(str(ln.credit)) - Decimal(str(ln.debit)) for ln in lines), Decimal("0"))


def _receive(session, *, qty=10, cost=10):
    vendor = proc.create_vendor(session, name="Acme")
    p = inv.create_product(session, sku="W1", name="Widget", type=ProductType.INVENTORY)
    session.flush()
    inb = inv.create_inbound(session, received_date=JAN,
                             lines=[{"product_id": p.id, "qty": qty, "unit_cost": cost}])
    inv.post_inbound(session, inb.id)  # Dr Inventory / Cr GR-IR  (qty*cost)
    return vendor, inb


def test_matched_bill_clears_gr_ir(session):
    vendor, inb = _receive(session, qty=10, cost=10)  # GR-IR credit 100
    assert _gr_ir_balance(session) == Decimal("100.00")

    il = inb.lines[0]
    bill = acct.create_ap_bill(
        session, vendor_id=vendor.id, bill_date=JAN, vendor_invoice_no="INV-77",
        lines=[{"description": "widgets", "qty": 10, "unit_price": 10,
                "inbound_line_id": il.id}],
    )
    acct.match_ap_bill(session, bill.id)

    assert bill.match_status == APMatchStatus.MATCHED
    assert bill.status == APBillStatus.OPEN
    # GR/IR fully cleared, AP now carries the 100 liability
    assert _gr_ir_balance(session) == Decimal("0.00")
    assert _ap_balance(session) == Decimal("100.00")


def test_mismatched_bill_flagged_exception_no_posting(session):
    vendor, inb = _receive(session, qty=10, cost=10)  # received 100
    il = inb.lines[0]
    bill = acct.create_ap_bill(
        session, vendor_id=vendor.id, bill_date=JAN,
        lines=[{"description": "widgets", "qty": 10, "unit_price": 12,  # billed 120 != 100
                "inbound_line_id": il.id}],
    )
    acct.match_ap_bill(session, bill.id)

    assert bill.match_status == APMatchStatus.EXCEPTION
    assert bill.status == APBillStatus.DRAFT
    # nothing posted -> GR/IR still outstanding, AP untouched
    assert _gr_ir_balance(session) == Decimal("100.00")
    assert _ap_balance(session) == Decimal("0.00")


def test_payment_settles_ap(session):
    vendor, inb = _receive(session, qty=10, cost=10)
    il = inb.lines[0]
    bill = acct.create_ap_bill(
        session, vendor_id=vendor.id, bill_date=JAN,
        lines=[{"qty": 10, "unit_price": 10, "inbound_line_id": il.id}],
    )
    acct.match_ap_bill(session, bill.id)
    assert _ap_balance(session) == Decimal("100.00")

    # partial payment 40
    acct.create_payment(session, vendor_id=vendor.id, payment_date=JAN,
                        applications=[{"ap_bill_id": bill.id, "amount": 40}])
    assert bill.balance == 60
    assert bill.status == APBillStatus.PARTIALLY_PAID
    assert _ap_balance(session) == Decimal("60.00")  # 100 - 40

    # pay the rest
    acct.create_payment(session, vendor_id=vendor.id, payment_date=JAN,
                        applications=[{"ap_bill_id": bill.id, "amount": 60}])
    assert bill.status == APBillStatus.PAID
    assert _ap_balance(session) == Decimal("0.00")


def test_cannot_pay_a_draft_bill(session):
    """A draft bill hasn't posted its AP liability to the GL; paying it would credit
    cash against an unrecognized payable. create_payment must refuse it."""
    vendor, inb = _receive(session, qty=10, cost=10)
    il = inb.lines[0]
    bill = acct.create_ap_bill(
        session, vendor_id=vendor.id, bill_date=JAN,
        lines=[{"qty": 10, "unit_price": 10, "inbound_line_id": il.id}],
    )
    # not matched/posted -> still DRAFT
    assert bill.status == APBillStatus.DRAFT
    with pytest.raises(ValueError, match="draft"):
        acct.create_payment(session, vendor_id=vendor.id, payment_date=JAN,
                            applications=[{"ap_bill_id": bill.id, "amount": 100}])
    # AP liability never moved
    assert _ap_balance(session) == Decimal("0.00")


def test_full_procure_to_pay_nets_to_cash_and_inventory(session):
    """After receive -> match -> pay: GR/IR=0, AP=0, inventory carries the cost,
    cash is reduced. The clearing account did its job."""
    vendor, inb = _receive(session, qty=5, cost=20)  # 100
    il = inb.lines[0]
    bill = acct.create_ap_bill(session, vendor_id=vendor.id, bill_date=JAN,
                               lines=[{"qty": 5, "unit_price": 20, "inbound_line_id": il.id}])
    acct.match_ap_bill(session, bill.id)
    acct.create_payment(session, vendor_id=vendor.id, payment_date=JAN,
                        applications=[{"ap_bill_id": bill.id, "amount": 100}])

    assert _gr_ir_balance(session) == Decimal("0.00")
    assert _ap_balance(session) == Decimal("0.00")
    # inventory asset on the books at 100
    inv_acc = acct.get_account_by_role(session, "inventory").id
    inv_lines = session.scalars(select(JournalLine).where(JournalLine.account_id == inv_acc)).all()
    inv_bal = sum((Decimal(str(ln.debit)) - Decimal(str(ln.credit)) for ln in inv_lines), Decimal("0"))
    assert inv_bal == Decimal("100.00")
