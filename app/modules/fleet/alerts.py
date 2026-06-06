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
    task = q.enqueue(
        session, to_role=Role.INSIGHT, category="anomaly_alert",
        title=f"이상 징후 {len(found)}건 감지", source=TaskSource.AGENT,
        from_role=Role.SYSTEM, idempotency_key=f"anomaly:{as_of.isoformat()}",
    )
    if task.status == TaskStatus.QUEUED:
        q.request_approval(session, task, result={
            "anomalies": found, "count": len(found),
            "note": "검토용 알림입니다. 확인했으면 승인(닫기)하세요.",
        })
    return task
