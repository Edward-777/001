"""fleet.miner — the learning loop's producer (docs/ADR.md §10).

Scans decisions and data the system already recorded for patterns worth turning
into rules, and PROPOSES each one as a draft card in the founder's approval
inbox. Deterministic scans only — no LLM in the loop.

v1 miner: duplicate-vendor aliases. Observed failure mode: an uploaded invoice
says 'Office Depot, Inc.' while the master data has 'Office Depot' — the spend
role auto-creates a duplicate vendor and the books split across the two. The
miner detects vendors sharing a normalized name and proposes: alias the name to
the canonical vendor + deactivate the duplicate. Approval activates the rule;
the next invoice from that vendor resolves correctly (counted in applied_count).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..learning import service as learn
from ..procurement import service as proc
from . import service as q
from .models import Role, TaskSource, TaskStatus


def mine_vendor_aliases(session: Session) -> int:
    """Propose one learned_rule task per duplicate-vendor group. Idempotent via
    the task idempotency_key — a rejected proposal is never re-raised."""
    groups: dict[str, list] = {}
    for v in proc.list_vendors(session):  # active vendors only
        key = learn.normalize_vendor_name(v.name)
        if key:
            groups.setdefault(key, []).append(v)

    proposed = 0
    for key, vendors in groups.items():
        if len(vendors) < 2:
            continue
        vendors.sort(key=lambda v: v.id)
        canonical, duplicates = vendors[0], vendors[1:]
        for dup in duplicates:
            task = q.enqueue(
                session,
                to_role=Role.INSIGHT,
                category="learned_rule",
                title=f"Learned rule: treat '{dup.name}' as '{canonical.name}'",
                source=TaskSource.AGENT,
                from_role=Role.SYSTEM,
                idempotency_key=f"learned_rule:vendor_alias:{dup.id}",
                payload={},
            )
            if task.status != TaskStatus.QUEUED or task.result:
                continue  # already proposed / decided earlier — respect it
            q.request_approval(session, task, result={
                "kind": "vendor_alias",
                "params": {"alias_normalized": key, "canonical_vendor_id": canonical.id},
                "deactivate_vendor_ids": [dup.id],
                "evidence": (f"Vendors #{canonical.id} '{canonical.name}' and #{dup.id} "
                             f"'{dup.name}' share the normalized name '{key}'. "
                             f"'{dup.name}' looks auto-created from a parsed document."),
                "note": (f"Approving: future documents naming '{dup.name}' resolve to "
                         f"'{canonical.name}', and the duplicate vendor is deactivated. "
                         "Rejecting: nothing changes and this is never proposed again."),
            })
            proposed += 1
    return proposed


def mine(session: Session) -> int:
    """All miners. Called by the work loop; must be cheap and idempotent."""
    return mine_vendor_aliases(session)
