"""payments.service — prepare → (human executes at the bank) → confirm.

Two hard rules, both test-pinned:
1. Preparing an instruction changes NOTHING in the books — it is a packet of
   where/how-much/why with the evidence chain attached.
2. The payment journal posts only on CONFIRMATION, which requires the human's
   paid date. The system records executions; it never performs them.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.money import money
from ..accounting import service as acct
from ..auth.models import User
from ..procurement.models import Vendor
from .models import InstructionStatus, PaymentInstruction


def prepare_instruction(session: Session, *, bill_no: str,
                        amount=None, user: User | None = None) -> PaymentInstruction:
    """Build the packet a human needs to release money: payee, remit-to,
    amount, wire reference, and the evidence chain (PO, match, due date)."""
    bill = acct.get_ap_bill_by_no(session, bill_no)
    if bill is None:
        raise ValueError(f"bill {bill_no!r} not found")
    if bill.status == "draft":
        raise ValueError(f"bill {bill.bill_no} is still a draft — it must be "
                         "posted/approved before payment is even instructed")
    if money(bill.balance) <= 0:
        raise ValueError(f"bill {bill.bill_no} is already settled")
    amt = money(amount) if amount is not None else money(bill.balance)
    if amt <= 0 or amt > money(bill.balance):
        raise ValueError(f"amount must be within the open balance "
                         f"({bill.balance})")
    existing = session.scalar(select(PaymentInstruction).where(
        PaymentInstruction.bill_id == bill.id,
        PaymentInstruction.status == str(InstructionStatus.PREPARED)))
    if existing is not None:
        raise ValueError(f"an instruction for {bill.bill_no} is already "
                         f"prepared (#{existing.id}) — confirm or cancel it first")

    vendor = session.get(Vendor, bill.vendor_id)
    po_no = None
    if bill.po_id:
        from ..procurement.models import PurchaseOrder
        po = session.get(PurchaseOrder, bill.po_id)
        po_no = po.po_no if po else None

    instr = PaymentInstruction(
        bill_id=bill.id, vendor_id=bill.vendor_id, amount=amt,
        remit_to=(vendor.remit_to if vendor else None),
        reference=f"{bill.bill_no}"
                  + (f" / {bill.vendor_invoice_no}" if bill.vendor_invoice_no else ""),
        evidence={
            "bill_no": bill.bill_no,
            "vendor_invoice_no": bill.vendor_invoice_no,
            "vendor_name": vendor.name if vendor else None,
            "amount": str(amt),
            "open_balance": str(bill.balance),
            "due_date": str(bill.due_date) if bill.due_date else None,
            "po_no": po_no,
            "match_status": bill.match_status,
            "match_note": getattr(bill, "match_note", None),
        },
        prepared_by=user.id if user else None,
    )
    session.add(instr)
    session.flush()
    audit.record(session, actor_user_id=user.id if user else None,
                 action="create", entity_type="payment_instruction",
                 entity_id=instr.id,
                 detail={"bill_no": bill.bill_no, "amount": str(amt)})
    return instr


def confirm_executed(session: Session, instruction_id: int, *, user: User,
                     paid_date: date, payment_ref: str | None = None) -> PaymentInstruction:
    """The human states the transfer WAS executed — only now does the payment
    journal post (Dr AP / Cr Cash), via the same accounting path as ever."""
    instr = session.get(PaymentInstruction, instruction_id)
    if instr is None:
        raise ValueError("payment instruction not found")
    if instr.status != str(InstructionStatus.PREPARED):
        raise ValueError(f"instruction is '{instr.status}', not prepared")
    if paid_date > date.today():
        raise ValueError("paid_date cannot be in the future — confirm only "
                         "executions that actually happened")
    pay = acct.create_payment(
        session, vendor_id=instr.vendor_id,
        applications=[{"ap_bill_id": instr.bill_id, "amount": instr.amount}],
        payment_date=paid_date)
    instr.status = str(InstructionStatus.CONFIRMED)
    instr.confirmed_by = user.id
    instr.confirmed_at = datetime.now(timezone.utc)
    instr.paid_date = paid_date
    instr.payment_ref = (payment_ref or "")[:120] or None
    instr.payment_no = pay.payment_no
    session.flush()
    audit.record(session, actor_user_id=user.id, action="post",
                 entity_type="payment_instruction", entity_id=instr.id,
                 detail={"payment_no": pay.payment_no, "paid_date": str(paid_date),
                         "payment_ref": instr.payment_ref})
    return instr


def cancel_instruction(session: Session, instruction_id: int, *,
                       user: User | None = None) -> PaymentInstruction:
    instr = session.get(PaymentInstruction, instruction_id)
    if instr is None:
        raise ValueError("payment instruction not found")
    if instr.status != str(InstructionStatus.PREPARED):
        raise ValueError(f"instruction is '{instr.status}', not prepared")
    instr.status = str(InstructionStatus.CANCELED)
    session.flush()
    audit.record(session, actor_user_id=user.id if user else None,
                 action="update", entity_type="payment_instruction",
                 entity_id=instr.id, detail={"status": "canceled"})
    return instr


def list_instructions(session: Session, *, open_only: bool = False,
                      limit: int = 50) -> list[PaymentInstruction]:
    stmt = select(PaymentInstruction).order_by(PaymentInstruction.id.desc())
    if open_only:
        stmt = stmt.where(
            PaymentInstruction.status == str(InstructionStatus.PREPARED))
    return list(session.scalars(stmt.limit(limit)))
