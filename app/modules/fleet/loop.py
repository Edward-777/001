"""fleet.loop — the single work loop (docs/AGENT-FLEET.md §3).

One loop drains the queue, processing each task as its assigned role (wearing the
to_role's handler). Roles without a handler yet (future phases) are simply left
queued. On a single local GPU this is naturally sequential — fine at startup
scale. Each tick is bounded by `max_tasks` so a flood can't monopolize a cycle.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import roles
from . import service as q


def run_once(session: Session, *, max_tasks: int = 100) -> int:
    """Process queued tasks for every role that has a handler. Returns the count
    processed. A handler must move its task off QUEUED; if it doesn't, we stop
    that role to avoid reprocessing the same row forever."""
    # Learning-loop producer: propose rules mined from recorded human resolutions
    # (idempotent, deterministic; mining must never break the work loop).
    from . import miner
    try:
        miner.mine(session)
    except Exception:
        pass

    processed = 0
    for role, handler in roles.HANDLERS.items():
        while processed < max_tasks:
            task = q.next_queued(session, to_role=role)
            if task is None:
                break
            q.claim(session, task)
            try:
                handler(session, task)
            except Exception as exc:  # a bad task must not kill the loop
                q.fail(session, task, reason=f"{type(exc).__name__}: {exc}")
            processed += 1
            if task.status == "queued":  # handler bug: would loop forever
                q.fail(session, task, reason="handler left task queued")
                break
    return processed
