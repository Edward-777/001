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
    Never posts; that waits for the founder (spend_approve). When the invoice
    names a PO whose goods were received, the draft is set up for a 3-way match."""
    from decimal import Decimal

    from ..inventory import service as inv

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

    # The vision parser extracts the PO number the invoice references — use it.
    po_number = str(parsed.get("po_number") or "").strip()
    po = proc.get_po_by_no(session, po_number) if po_number else None
    receipt_lines = []
    if po is not None:
        receipt_lines = [ln for inb in inv.list_posted_inbounds_for_po(session, po.id)
                         for ln in inb.lines]

    invoice_no = parsed.get("invoice_no")
    po_matched = False
    notes: list[str] = []
    lines = [{"description": f"{vendor_name} invoice {invoice_no or ''}".strip(),
              "qty": 1, "unit_price": total}]
    if po is not None and receipt_lines:
        received_value = sum(
            (Decimal(str(ln.qty_received)) * Decimal(str(ln.unit_cost)) for ln in receipt_lines),
            Decimal("0"),
        )
        if abs(received_value - Decimal(str(total))) <= Decimal("0.01"):
            # bill mirrors the receipts -> approving runs the 3-way match
            lines = [{"description": f"{vendor_name} invoice {invoice_no or ''} (receipt match)".strip(),
                      "qty": ln.qty_received, "unit_price": ln.unit_cost,
                      "inbound_line_id": ln.id} for ln in receipt_lines]
            po_matched = True
            notes.append(f"{po.po_no} matched — approving runs the 3-way match (clears GR/IR).")
        else:
            notes.append(f"invoice ${total} vs received ${received_value} on {po.po_no} — "
                         "resolve the variance before approving.")
    elif po is not None:
        notes.append(f"{po.po_no} exists but no goods receipt is posted — approve to expense "
                     "now, or receive the goods first and re-upload to 3-way match.")
    elif po_number:
        notes.append(f"invoice references PO '{po_number}' — no such PO found.")
    if po is not None and po.vendor_id and po.vendor_id != vendor.id:
        notes.append(f"⚠ vendor on the invoice differs from the vendor on {po.po_no}.")

    bill = acct.create_ap_bill(
        session,
        vendor_id=vendor.id,
        vendor_invoice_no=invoice_no,
        po_id=po.id if po else None,
        lines=lines,
    )
    suggested = _suggest_expense_account(session)
    goods_received = payload.get("goods_received")
    if not notes:
        if goods_received is False:
            notes.append("Goods not received yet — on approval this posts as a direct expense, "
                         "or you can wait for the goods-receipt number to 3-way match it.")
        else:
            notes.append("Looks like a service / direct cost. Approving posts it to the "
                         "suggested account.")

    q.request_approval(session, task, result={
        "draft_bill_id": bill.id,
        "bill_no": bill.bill_no,
        "vendor_id": vendor.id,
        "vendor_name": vendor.name,
        "new_vendor": new_vendor,
        "amount": str(bill.amount),
        "po_no": po.po_no if po else None,
        "po_matched": po_matched,
        "suggested_account_code": suggested.code if suggested else None,
        "suggested_account_name": suggested.name if suggested else None,
        "goods_received": goods_received,
        "note": " ".join(notes),
    })


def spend_approve(session: Session, task: Task) -> None:
    """Founder approved the draft bill. PO-matched bills run the 3-way match
    (an EXCEPTION never posts); everything else posts as a direct bill."""
    result = task.result or {}
    bill_id = result.get("draft_bill_id")
    if result.get("po_matched"):
        bill = acct.match_ap_bill(session, bill_id)
        if bill.match_status == "exception":
            q.fail(session, task, reason=f"3-way match failed: {bill.match_note}")
            return
        q.resolve_approval(session, task, approved=True)
        return
    code = result.get("suggested_account_code")
    account = acct.get_account_by_code(session, code) if code else None
    if bill_id is None or account is None:
        q.fail(session, task, reason="cannot post: missing draft bill or account")
        return
    acct.post_direct_bill(session, bill_id, account.id)
    q.resolve_approval(session, task, approved=True)


# ---- 📦 supply (packing list -> draft goods receipt) ---------------------

def supply_handle(session: Session, task: Task) -> None:
    """packing_list -> DRAFT inbound (unposted) matched to an open PO, parked for
    approval. Valuation comes from the PO line prices (packing lists carry no
    prices). Any ambiguity — no PO, several candidate POs, unmapped or over-
    shipped lines — fails loudly to a human; the role never guesses (default-deny)."""
    from decimal import Decimal

    from ..inventory import service as inv

    payload = task.payload or {}
    parsed = payload.get("parsed", payload)
    vendor_name = (parsed.get("vendor_name") or "").strip()
    parsed_lines = parsed.get("lines") or []
    if not parsed_lines:
        q.fail(session, task, reason="packing list has no readable lines — needs a human")
        return

    # 1) resolve the PO: explicit po_number, else the vendor's single receivable PO
    po = None
    po_number = str(parsed.get("po_number") or "").strip()
    if po_number:
        po = proc.get_po_by_no(session, po_number)
        if po is None:
            q.fail(session, task, reason=f"delivery references PO '{po_number}' — no such PO")
            return
    else:
        vendor = proc.find_vendor_by_name(session, vendor_name) if vendor_name else None
        if vendor is not None:
            candidates = [p for p in proc.list_pos(session)
                          if p.vendor_id == vendor.id
                          and p.status in ("open", "partially_received")]
            if len(candidates) == 1:
                po = candidates[0]
        if po is None:
            q.fail(session, task, reason="cannot match this delivery to a single open PO "
                                         "— needs a human")
            return
    if po.status not in ("open", "partially_received"):
        q.fail(session, task, reason=f"{po.po_no} is {po.status} — cannot receive against it")
        return

    # 2) map parsed lines -> PO lines (by SKU, then description containment)
    allocations, receipt_lines = [], []
    for ln in parsed_lines:
        target = None
        sku = (ln.get("sku") or "").strip()
        if sku:
            product = inv.get_product_by_sku(session, sku)
            if product is not None:
                target = next((pl for pl in po.lines if pl.product_id == product.id), None)
        if target is None:
            desc = (ln.get("description") or "").lower()
            target = next((pl for pl in po.lines
                           if pl.description and (pl.description.lower() in desc
                                                  or desc in pl.description.lower())), None)
        if target is None or target.product_id is None:
            q.fail(session, task, reason=f"cannot map delivery line '{ln.get('description')}' "
                                         f"to a line on {po.po_no} — needs a human")
            return
        qty = Decimal(str(ln.get("qty") or 0))
        if qty <= 0:
            q.fail(session, task, reason=f"line '{ln.get('description')}' has no quantity")
            return
        allocations.append({"po_line_id": target.id, "qty": qty})
        receipt_lines.append({"product_id": target.product_id, "qty": qty,
                              "unit_cost": target.unit_price,  # PO price, never guessed
                              "po_line_id": target.id})

    # 3) over-receipt check (same policy as chat receiving: reject)
    errors = proc.validate_receipt_against_po(po, allocations)
    if errors:
        q.fail(session, task, reason=errors[0] + " — needs a human")
        return

    # 4) DRAFT inbound only — posting waits for the founder (supply_approve)
    inb = inv.create_inbound(session, po_id=po.id, lines=receipt_lines)
    q.request_approval(session, task, result={
        "inbound_id": inb.id,
        "inbound_no": inb.inbound_no,
        "po_no": po.po_no,
        "vendor_name": vendor_name,
        "amount": str(sum((r["qty"] * Decimal(str(r["unit_cost"])) for r in receipt_lines),
                          Decimal("0"))),
        "lines": [{"description": ln.get("description"), "qty": str(ln.get("qty"))}
                  for ln in parsed_lines],
        "note": (f"Approving posts goods receipt {inb.inbound_no} against {po.po_no}: "
                 "stock in + Dr Inventory / Cr GR-IR, and updates the PO."),
    })


def supply_approve(session: Session, task: Task) -> None:
    """Founder approved the draft receipt -> post it. The InboundPosted handler
    rolls POLine.qty_received and the PO status."""
    from ..inventory import service as inv

    result = task.result or {}
    inbound_id = result.get("inbound_id")
    if inbound_id is None:
        q.fail(session, task, reason="cannot post: missing draft inbound")
        return
    inv.post_inbound(session, inbound_id)
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
        "note": "Approving issues the customer invoice and recognizes revenue (Dr AR / Cr Revenue).",
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
    """Founder approval for accounting tasks: pay the weekly run, or lock a month."""
    result = task.result or {}
    if task.category == "payment_run":
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
    elif task.category == "month_close":
        period = result.get("period")
        if period:
            acct.close_period(session, period)  # locks the month
    q.resolve_approval(session, task, approved=True)


# ---- role registries ----------------------------------------------------

# role -> handler that processes a freshly claimed task
HANDLERS: dict[str, Callable[[Session, Task], None]] = {
    Role.SPEND: spend_handle,
    Role.REVENUE: revenue_handle,
    Role.SUPPLY: supply_handle,
}

# role -> approver that does the real side-effect when the founder approves
APPROVERS: dict[str, Callable[[Session, Task], None]] = {
    Role.SPEND: spend_approve,
    Role.REVENUE: revenue_approve,
    Role.SUPPLY: supply_approve,
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
