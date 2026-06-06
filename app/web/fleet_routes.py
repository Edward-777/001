"""Fleet control panel — the founder's approval inbox (docs/AGENT-FLEET.md §5).

The work loop drafts; the founder approves here. Listing is login-gated; the
approve action posts to the ledger, so it requires finance authority (the same
gate the AI's report/posting tools use).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth import service as auth
from ..modules.fleet import loop, roles
from ..modules.fleet import service as q
from ..modules.fleet.models import TaskStatus
from .deps import require_login, require_scope, templates

router = APIRouter()

# Acting on drafts (run the loop, approve/post, reject) is a finance action —
# the inbox is the SINGLE control point for all autonomous work, so gate every
# mutating route at finance L3 (same level as paying a bill). Viewing is open.
_finance = require_scope("finance", 3)


def _can_finance(user) -> bool:
    return auth.can_access(auth.get_grants(user), "finance", 3)


@router.get("/fleet", response_class=HTMLResponse)
def fleet_inbox(request: Request, user=Depends(require_login),
                session: Session = Depends(get_session)):
    pending = q.pending_approvals(session)
    queued = q.list_tasks(session, status=TaskStatus.QUEUED)
    return templates.TemplateResponse(request, "fleet.html", {
        "user": user, "pending": pending, "queued": queued,
        "can_finance": _can_finance(user),
    })


@router.post("/fleet/run")
def fleet_run(user=Depends(_finance), session: Session = Depends(get_session)):
    """Manually tick the work loop (the scheduler does this automatically in prod)."""
    loop.run_once(session)
    return RedirectResponse("/fleet", status_code=303)


@router.post("/fleet/{task_id}/approve")
def fleet_approve(task_id: int, user=Depends(_finance),
                  session: Session = Depends(get_session)):
    task = q.get_task(session, task_id)
    if task is not None and task.status == TaskStatus.NEEDS_APPROVAL:
        roles.resolve(session, task, approved=True)
    return RedirectResponse("/fleet", status_code=303)


@router.post("/fleet/{task_id}/reject")
def fleet_reject(task_id: int, user=Depends(_finance),
                 session: Session = Depends(get_session)):
    task = q.get_task(session, task_id)
    if task is not None and task.status == TaskStatus.NEEDS_APPROVAL:
        roles.resolve(session, task, approved=False)
    return RedirectResponse("/fleet", status_code=303)
