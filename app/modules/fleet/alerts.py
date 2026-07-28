"""fleet.alerts — the 📊 insight proactive push (docs/AGENT-FLEET.md §2).

A scheduled producer runs anomaly detection and, if anything looks off, parks a
single informational alert in the founder's inbox. Idempotent per day. The alert
has no side-effect: approving just acknowledges (closes) it.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..accounting import service as acct
from . import service as q
from .models import Role, TaskSource, TaskStatus


def enqueue_anomaly_alerts(session: Session, *, as_of: date | None = None):
    """Detect anomalies and, if any, park one alert for the founder. Returns the
    task or None when nothing unusual was found."""
    as_of = as_of or date.today()
    found = acct.detect_all(session, as_of=as_of)
    if not found:
        return None
    plural = "anomalies" if len(found) != 1 else "anomaly"
    task = q.enqueue(
        session, to_role=Role.INSIGHT, category="anomaly_alert",
        title=f"{len(found)} {plural} detected", source=TaskSource.AGENT,
        from_role=Role.SYSTEM, idempotency_key=f"anomaly:{as_of.isoformat()}",
    )
    if task.status == TaskStatus.QUEUED:
        q.request_approval(session, task, result={
            "anomalies": found, "count": len(found),
            "note": "Heads-up for review. Approve to acknowledge (close) it.",
        })
    return task


def enqueue_renewal_alerts(session: Session, *, as_of: date | None = None):
    """Contracts inside their notice window -> one informational card for the
    founder. Idempotent per week (renewals move slowly; a daily card is nagging),
    keyed on the set of due contracts so a NEW due contract re-alerts at once."""
    from ..contracts import service as contracts

    as_of = as_of or date.today()
    due = contracts.upcoming_renewals(session, as_of=as_of)
    if not due:
        return None
    ids = ",".join(str(r["contract_id"]) for r in due)
    plural = "contracts" if len(due) != 1 else "contract"
    task = q.enqueue(
        session, to_role=Role.INSIGHT, category="renewal_alert",
        title=f"{len(due)} {plural} up for renewal", source=TaskSource.AGENT,
        from_role=Role.SYSTEM,
        idempotency_key=f"renewal:{as_of.isocalendar().year}"
                        f"-w{as_of.isocalendar().week}:{ids}",
    )
    if task.status == TaskStatus.QUEUED:
        q.request_approval(session, task, result={
            "renewals": due, "count": len(due),
            "note": "Renewal window reached. Approve to acknowledge; manage the "
                    "contracts at /contracts.",
        })
    return task
