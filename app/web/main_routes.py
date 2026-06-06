"""Main app pages: dashboard, requests, approvals, notifications, financials.

Auth/authz is enforced via dependencies (require_login / require_scope) — no
per-handler guard boilerplate. Own-data pages need login; company financials
require the finance scope (P0-1)."""
from __future__ import annotations

import asyncio
import json
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_session
from ..modules.accounting import service as acct
from ..modules.approval import service as appr
from ..modules.approval.models import RequestType
from ..modules.notifications import service as notify
from .deps import require_login, require_scope, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_login), session: Session = Depends(get_session)):
    from ..modules.auth import service as auth
    from ..modules.fleet import service as fleet_q

    pending = appr.pending_for_user(session, user.id)
    unread = notify.unread_count(session, user.id)
    my_reqs = appr.list_requests_for_user(session, user.id, limit=5)

    # The 📊 cash-insight headline + fleet approval count — finance users only.
    runway = fleet_pending = None
    if auth.can_access(auth.get_grants(user), "finance", 3):
        runway = acct.cash_runway(session)
        fleet_pending = len(fleet_q.pending_approvals(session))
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "pending": pending, "unread": unread, "my_reqs": my_reqs,
        "runway": runway, "fleet_pending": fleet_pending,
    })


@router.get("/requests", response_class=HTMLResponse)
def requests_list(request: Request, user=Depends(require_login), session: Session = Depends(get_session)):
    reqs = appr.list_requests_for_user(session, user.id)
    return templates.TemplateResponse(request, "requests_list.html", {"user": user, "reqs": reqs})


@router.get("/requests/new", response_class=HTMLResponse)
def request_new(request: Request, user=Depends(require_login)):
    return templates.TemplateResponse(request, "request_new.html", {"user": user})


@router.post("/requests")
def request_create(
    title: str = Form(...),
    type: str = Form("purchase"),
    description: str = Form(""),
    qty: float = Form(1),
    unit_price: float = Form(0),
    user=Depends(require_login),
    session: Session = Depends(get_session),
):
    req = appr.create_request(
        session, type=RequestType(type), requester_id=user.id, title=title,
        description=description, lines=[{"description": description or title, "qty": qty, "unit_price": unit_price}],
    )
    appr.submit_request(session, req.id)
    return RedirectResponse("/requests", status_code=303)


@router.get("/approvals", response_class=HTMLResponse)
def approvals_inbox(request: Request, user=Depends(require_login), session: Session = Depends(get_session)):
    pending = appr.pending_for_user(session, user.id)
    return templates.TemplateResponse(request, "approvals.html", {"user": user, "pending": pending})


@router.post("/approvals/{request_id}/approve")
def approve(request_id: int, user=Depends(require_login), session: Session = Depends(get_session)):
    appr.approve(session, request_id, user.id)
    return RedirectResponse("/approvals", status_code=303)


@router.post("/approvals/{request_id}/reject")
def reject(request_id: int, comment: str = Form(""), user=Depends(require_login),
           session: Session = Depends(get_session)):
    appr.reject(session, request_id, user.id, comment=comment)
    return RedirectResponse("/approvals", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, user=Depends(require_login), session: Session = Depends(get_session)):
    items = notify.list_for_user(session, user.id)
    notify.mark_all_read(session, user.id)
    return templates.TemplateResponse(request, "notifications.html", {"user": user, "items": items})


@router.get("/notifications/unread")
def notifications_unread(user=Depends(require_login), session: Session = Depends(get_session)):
    return {"unread": notify.unread_count(session, user.id)}


@router.get("/notifications/stream")
async def notifications_stream(user=Depends(require_login)):
    """SSE: push the unread count periodically (each client opens its own session)."""
    user_id = user.id

    async def gen():
        for _ in range(6):  # bounded for safety; the client reconnects
            with SessionLocal() as s:
                n = notify.unread_count(s, user_id)
            yield f"data: {json.dumps({'unread': n})}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/reports/financials", response_class=HTMLResponse)
def financials(request: Request, period: str | None = None,
               user=Depends(require_scope("finance", 3)),  # DESIGN §8.5: ledger/financials = level 3
               session: Session = Depends(get_session)):
    period = period or date.today().strftime("%Y-%m")
    fin = acct.generate_financials(session, period)
    return templates.TemplateResponse(request, "financials.html", {"user": user, "fin": fin, "period": period})


# Required permission per report kind (DESIGN §8.5) — single source of truth in
# accounting.export, shared with the AI report tool so the gates can't drift.
_REPORT_PERMS = acct.REPORT_PERMS


@router.get("/reports/export")
def report_export(kind: str, period: str | None = None,
                  user=Depends(require_login), session: Session = Depends(get_session)):
    """Download a report as an .xlsx file. Permission-gated per kind (same gate
    the AI tool uses), so a download link can't bypass authorization."""
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    if kind not in _REPORT_PERMS:
        raise HTTPException(status_code=404, detail="unknown report")
    scope, level = _REPORT_PERMS[kind]
    from ..modules.auth import service as auth
    if not auth.can_access(auth.get_grants(user), scope, level):
        raise HTTPException(status_code=403, detail=f"requires {scope} level {level}")

    filename, data = acct.build_report_xlsx(session, kind, period)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
