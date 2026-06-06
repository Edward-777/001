"""fleet.payment_run — the weekly 💸 payment proposal (docs/AGENT-FLEET.md §4).

A scheduled producer gathers open vendor bills into one "this week's payments"
task parked for the founder. The founder pays in the bank, then approves; the
accounting approver records the disbursements (Dr AP / Cr Cash). Idempotent per
ISO week so a re-run never double-proposes.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..accounting import service as acct
from ..procurement import service as proc
from . import service as q
from .models import Role, TaskSource, TaskStatus


def enqueue_weekly_payment_run(session: Session, *, as_of: date | None = None):
    """Build (once per ISO week) the list of open bills to pay, parked for approval.
    Returns the task, or None if there's nothing to pay."""
    as_of = as_of or date.today()
    bills = [
        b for b in acct.list_open_bills(session)
        if b.status == "open" and Decimal(str(b.balance)) > 0
    ]
    if not bills:
        return None

    iso = as_of.isocalendar()
    key = f"payrun:{iso.year}-W{iso.week:02d}"
    items, total = [], Decimal("0")
    for b in bills:
        v = proc.get_vendor(session, b.vendor_id)
        bal = Decimal(str(b.balance))
        total += bal
        items.append({
            "ap_bill_id": b.id, "bill_no": b.bill_no, "vendor_id": b.vendor_id,
            "vendor": v.name if v else str(b.vendor_id), "amount": str(bal),
        })

    task = q.enqueue(
        session, to_role=Role.ACCOUNTING, category="payment_run",
        title=f"This week's payments — {len(items)} bills / ${total}",
        source=TaskSource.AGENT, from_role=Role.SYSTEM, idempotency_key=key,
    )
    if task.status == TaskStatus.QUEUED:  # freshly created this week -> park it
        q.request_approval(session, task, result={
            "bills": items, "total": str(total), "count": len(items),
            "note": "Pay these in your bank, then Approve to record the disbursements (Dr AP / Cr Cash).",
        })
    return task
