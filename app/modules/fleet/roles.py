"""fleet.roles — what each role *does* with a task (docs/AGENT-FLEET.md §9).

A role handler takes a claimed task and must move it off QUEUED: complete it,
park it for approval, bounce it, or fail it. Per the universal gate, handlers
only ever produce DRAFTS; the actual posting happens in the matching approver,
which runs when the founder approves.

Phase 1 ships the 💸 spend (vendor-bill) role. Other roles arrive in later phases.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounting import service as acct
from ..accounting.models import Account, AccountType
from ..procurement import service as proc
from ..sales import service as sls
from . import service as q
from .models import Role, Task

# Generic default expense account the spend role suggests; the founder confirms
# (or reassigns) on approval, so this is a starting suggestion, never a silent guess.
DEFAULT_EXPENSE_CODE = "6300"  # Office Supplies


def _suggest_expense_account(session: Session) -> Account | None:
    acct_ = acct.get_account_by_code(session, DEFAULT_EXPENSE_CODE)
    if acct_ is not None:
        return acct_
    return session.scalars(
        select(Account).where(Account.type == str(AccountType.EXPENSE)).order_by(Account.code)
    ).first()


# ---- 💸 spend (vendor bill) ---------------------------------------------

def spend_handle(session: Session, task: Task) -> None:
    """invoice/receipt -> draft AP bill + suggested account, parked for approval.
    Never posts; that waits for the founder (spend_approve)."""
    payload = task.payload or {}
    parsed = payload.get("parsed", payload)
    vendor_name = (parsed.get("vendor_name") or "").strip()
    total = parsed.get("total", parsed.get("amount"))
    if not vendor_name or total in (None, "", 0):
        q.fail(session, task, reason="invoice missing vendor name or total — needs a human")
        return

    vendor = proc.find_vendor_by_name(session, vendor_name)
    new_vendor = vendor is None
    if vendor is None:
        # master data, not a ledger action — safe to create now; surfaced to founder.
        vendor = proc.create_vendor(session, name=vendor_name)

    invoice_no = parsed.get("invoice_no")
    bill = acct.create_ap_bill(
        session,
        vendor_id=vendor.id,
        vendor_invoice_no=invoice_no,
        lines=[{"description": f"{vendor_name} invoice {invoice_no or ''}".strip(),
                "qty": 1, "unit_price": total}],
    )
    suggested = _suggest_expense_account(session)
    goods_received = payload.get("goods_received")
    if goods_received is False:
        note = ("물품 입고 전입니다 — 승인 시 직접 비용으로 기표되거나, 입고증을 받은 뒤 "
                "3-way 매칭하도록 잠시 보류할 수 있습니다.")
    else:
        note = "서비스/직접 비용으로 보입니다. 승인하면 추천 계정으로 기표합니다."

    q.request_approval(session, task, result={
        "draft_bill_id": bill.id,
        "bill_no": bill.bill_no,
        "vendor_id": vendor.id,
        "vendor_name": vendor.name,
        "new_vendor": new_vendor,
        "amount": str(bill.amount),
        "suggested_account_code": suggested.code if suggested else None,
        "suggested_account_name": suggested.name if suggested else None,
        "goods_received": goods_received,
        "note": note,
    })


def spend_approve(session: Session, task: Task) -> None:
    """Founder approved the draft bill -> post it (Dr expense / Cr AP), mark done."""
    result = task.result or {}
    bill_id = result.get("draft_bill_id")
    code = result.get("suggested_account_code")
    account = acct.get_account_by_code(session, code) if code else None
    if bill_id is None or account is None:
        q.fail(session, task, reason="cannot post: missing draft bill or account")
        return
    acct.post_direct_bill(session, bill_id, account.id)
    q.resolve_approval(session, task, approved=True)


# ---- 💰 revenue (customer invoice) --------------------------------------

def _find_customer(session: Session, name: str):
    low = name.strip().lower()
    for c in sls.list_customers(session):
        if low in c.name.lower():
            return c
    return None


def revenue_handle(session: Session, task: Task) -> None:
    """customer_invoice -> drafts a customer invoice, parked for approval. The AR
    invoice (which recognizes revenue) is NOT created until the founder approves —
    the draft lives in the task, so nothing hits the ledger early."""
    payload = task.payload or {}
    parsed = payload.get("parsed", payload)
    customer_name = (parsed.get("customer_name") or "").strip()
    lines = parsed.get("lines")
    total = parsed.get("total", parsed.get("amount"))
    if not customer_name or (not lines and total in (None, "", 0)):
        q.fail(session, task, reason="invoice missing customer name or amount — needs a human")
        return
    if not lines:
        lines = [{"description": parsed.get("description") or "Services",
                  "qty": 1, "unit_price": total}]

    customer = _find_customer(session, customer_name)
    new_customer = customer is None
    if customer is None:
        customer = sls.create_customer(session, name=customer_name)

    amount = sum(
        (Decimal(str(ln.get("qty", 1))) * Decimal(str(ln.get("unit_price", 0))) for ln in lines),
        Decimal("0"),
    )
    q.request_approval(session, task, result={
        "customer_id": customer.id,
        "customer_name": customer.name,
        "new_customer": new_customer,
        "lines": lines,
        "amount": str(amount),
        "note": "승인하면 고객 청구서를 발행하고 매출을 인식합니다 (외상매출금 / 매출).",
    })


def revenue_approve(session: Session, task: Task) -> None:
    """Founder approved -> post the AR invoice (Dr AR / Cr Revenue), mark done."""
    result = task.result or {}
    customer_id = result.get("customer_id")
    lines = result.get("lines")
    if customer_id is None or not lines:
        q.fail(session, task, reason="cannot post invoice: missing customer or lines")
        return
    invoice = sls.post_ar_invoice(session, customer_id=customer_id, lines=lines)
    # Copy FIRST, then assign a new dict — mutating task.result in place pollutes
    # SQLAlchemy's loaded snapshot, so the change wouldn't be detected/flushed.
    task.result = {**result, "invoice_no": invoice.invoice_no}
    q.resolve_approval(session, task, approved=True)


# ---- 📒 accounting (weekly payment run approval) ------------------------

def accounting_approve(session: Session, task: Task) -> None:
    """Founder approved the weekly payment run -> record each disbursement
    (Dr AP / Cr Cash). Only the payment_run category does work here."""
    if task.category != "payment_run":
        q.resolve_approval(session, task, approved=True)
        return
    result = task.result or {}
    paid = []
    for item in result.get("bills", []):
        bill = acct.get_ap_bill(session, item.get("ap_bill_id"))
        if bill is None or Decimal(str(bill.balance)) <= 0:
            continue
        acct.create_payment(
            session, vendor_id=bill.vendor_id,
            applications=[{"ap_bill_id": bill.id, "amount": bill.balance}],
        )
        paid.append(item.get("bill_no"))
    task.result = {**result, "paid": paid}
    q.resolve_approval(session, task, approved=True)


# ---- role registries ----------------------------------------------------

# role -> handler that processes a freshly claimed task
HANDLERS: dict[str, Callable[[Session, Task], None]] = {
    Role.SPEND: spend_handle,
    Role.REVENUE: revenue_handle,
}

# role -> approver that does the real side-effect when the founder approves
APPROVERS: dict[str, Callable[[Session, Task], None]] = {
    Role.SPEND: spend_approve,
    Role.REVENUE: revenue_approve,
    Role.ACCOUNTING: accounting_approve,
}


def resolve(session: Session, task: Task, *, approved: bool) -> None:
    """Apply the founder's decision to a parked (needs_approval) task."""
    if not approved:
        q.resolve_approval(session, task, approved=False)
        return
    approver = APPROVERS.get(task.to_role)
    if approver is not None:
        approver(session, task)  # does the posting AND marks the task done
    else:
        q.resolve_approval(session, task, approved=True)
