"""Accounts Payable service: vendor bills (3-way match) + payments.

3-way match compares the vendor bill against the goods actually received
(inbound lines). On a clean match it clears GR/IR:
    Dr GR/IR Clearing / Cr Accounts Payable.
Payment then settles the payable:  Dr Accounts Payable / Cr Cash.
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
from .ap_models import (
    APBill,
    APBillLine,
    APBillStatus,
    APMatchStatus,
    BillSource,
    Payment,
    PaymentApplication,
)
from .ledger_models import JournalSource
from .posting import apply_rule


def create_ap_bill(
    session: Session,
    *,
    vendor_id: int,
    lines: list[dict],
    po_id: int | None = None,
    vendor_invoice_no: str | None = None,
    bill_date: date | None = None,
    due_date: date | None = None,
    source: BillSource = BillSource.MANUAL,
    attachment_path: str | None = None,
) -> APBill:
    """lines: [{description, qty, unit_price, inbound_line_id?}]."""
    bill = APBill(
        bill_no=next_number(session, "BILL", _year()),
        vendor_invoice_no=vendor_invoice_no,
        vendor_id=vendor_id,
        po_id=po_id,
        bill_date=bill_date or date.today(),
        due_date=due_date,
        source=str(source),
        status=str(APBillStatus.DRAFT),
        match_status=str(APMatchStatus.UNMATCHED),
    )
    session.add(bill)
    session.flush()

    amount = Decimal("0")
    for ln in lines:
        qty = Decimal(str(ln.get("qty", 0)))
        price = Decimal(str(ln.get("unit_price", 0)))
        line_amt = (qty * price).quantize(_CENTS)
        amount += line_amt
        session.add(
            APBillLine(
                ap_bill_id=bill.id,
                inbound_line_id=ln.get("inbound_line_id"),
                description=ln.get("description"),
                qty=qty,
                unit_price=price,
                amount=line_amt,
            )
        )
    bill.amount = amount
    bill.balance = amount
    session.flush()
    return bill


def match_ap_bill(session: Session, bill_id: int) -> APBill:
    """3-way match: compare the bill to goods received. On a clean match, clear
    GR/IR (Dr GR/IR / Cr AP) and open the bill; otherwise flag an exception."""
    bill = session.get(APBill, bill_id)
    if bill is None or bill.status != APBillStatus.DRAFT:
        raise ValueError("bill not in draft")

    received = Decimal("0")
    linked = False
    for line in bill.lines:
        if line.inbound_line_id is None:
            continue
        linked = True
        il = inv.get_inbound_line(session, line.inbound_line_id)
        if il is not None:
            received += (Decimal(str(il.qty_received)) * Decimal(str(il.unit_cost))).quantize(_CENTS)

    bill_amount = Decimal(str(bill.amount))
    if linked and bill_amount > 0 and abs(received - bill_amount) <= _CENTS:
        apply_rule(
            session,
            event_type="ap_bill.matched",
            amount=bill_amount,
            entry_date=bill.bill_date or date.today(),
            description=f"AP bill match #{bill.id} (clear GR/IR)",
            source_type=JournalSource.AP_BILL,
            source_id=bill.id,
        )
        bill.match_status = str(APMatchStatus.MATCHED)
        bill.status = str(APBillStatus.OPEN)
    else:
        bill.match_status = str(APMatchStatus.EXCEPTION)
    session.flush()
    return bill


def get_ap_bill(session: Session, bill_id: int) -> APBill | None:
    return session.get(APBill, bill_id)


def get_ap_bill_by_no(session: Session, bill_no: str) -> APBill | None:
    return session.scalar(select(APBill).where(APBill.bill_no == bill_no))


def list_open_bills(session: Session) -> list[APBill]:
    return list(session.scalars(select(APBill).where(APBill.balance > 0)))


def create_payment(
    session: Session,
    *,
    vendor_id: int,
    applications: list[dict],
    payment_date: date | None = None,
    method: str | None = None,
    bank_account_id: int | None = None,
) -> Payment:
    """applications: [{ap_bill_id, amount}] — settles each payable. Dr AP / Cr Cash."""
    pdate = payment_date or date.today()
    total = sum((Decimal(str(a["amount"])) for a in applications), Decimal("0")).quantize(_CENTS)
    pay = Payment(
        payment_no=next_number(session, "PAY", _year()),
        vendor_id=vendor_id,
        payment_date=pdate,
        amount=total,
        method=method,
        bank_account_id=bank_account_id,
    )
    session.add(pay)
    session.flush()

    for a in applications:
        amt = Decimal(str(a["amount"]))
        bill = session.get(APBill, a["ap_bill_id"])
        if bill is None:
            raise ValueError("bill not found")
        new_balance = (Decimal(str(bill.balance)) - amt).quantize(_CENTS)
        bill.balance = new_balance
        bill.status = str(APBillStatus.PAID if new_balance <= 0 else APBillStatus.PARTIALLY_PAID)
        session.add(
            PaymentApplication(payment_id=pay.id, ap_bill_id=bill.id, applied_amount=amt)
        )
    session.flush()

    apply_rule(
        session,
        event_type="payment.posted",
        amount=total,
        entry_date=pdate,
        description=f"Vendor payment #{pay.id}",
        source_type=JournalSource.PAYMENT,
        source_id=pay.id,
    )
    return pay
