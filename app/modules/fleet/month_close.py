"""fleet.month_close — monthly close proposal (docs/AGENT-FLEET.md §4).

At month start a producer summarizes the just-ended month (net income, totals,
subledger→GL tie-out) and parks it for the founder. Approving locks the period
(no more posting into it). Idempotent per period; empty months are skipped.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..accounting import service as acct
from . import service as q
from .models import Role, TaskSource, TaskStatus


def enqueue_month_close(session: Session, *, as_of: date | None = None):
    """Propose closing the PREVIOUS month. Returns the task, or None if that month
    had no activity."""
    as_of = as_of or date.today()
    prev_end = date(as_of.year, as_of.month, 1) - timedelta(days=1)
    period = f"{prev_end.year:04d}-{prev_end.month:02d}"

    fin = acct.generate_financials(session, period)
    is_, bs = fin["income_statement"], fin["balance_sheet"]
    if (Decimal(str(is_["total_revenue"])) == 0 and Decimal(str(is_["total_expenses"])) == 0
            and Decimal(str(bs["total_assets"])) == 0):
        return None  # nothing happened that month

    tie = acct.subledger_check(session, as_of=prev_end)
    task = q.enqueue(
        session, to_role=Role.ACCOUNTING, category="month_close",
        title=f"{period} month-end close", source=TaskSource.AGENT,
        from_role=Role.SYSTEM, idempotency_key=f"close:{period}",
    )
    if task.status == TaskStatus.QUEUED:
        q.request_approval(session, task, result={
            "period": period,
            "net_income": str(is_["net_income"]),
            "total_assets": str(bs["total_assets"]),
            "balanced": bs["balanced"],
            "subledger_ties_out": tie.get("all_ok", True),
            "note": "Approving closes (locks) this month — no further postings can be made into it.",
        })
    return task
