"""Main app pages: dashboard, requests, approvals, notifications, financials."""
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
from .deps import get_current_user, templates

router = APIRouter()


def _guard(user):
    return None if user else RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    pending = appr.pending_for_user(session, user.id)
    unread = notify.unread_count(session, user.id)
    my_reqs = appr.list_requests_for_user(session, user.id, limit=5)
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "pending": pending, "unread": unread, "my_reqs": my_reqs,
    })


@router.get("/requests", response_class=HTMLResponse)
def requests_list(request: Request, user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    reqs = appr.list_requests_for_user(session, user.id)
    return templates.TemplateResponse(request, "requests_list.html", {"user": user, "reqs": reqs})


@router.get("/requests/new", response_class=HTMLResponse)
def request_new(request: Request, user=Depends(get_current_user)):
    if (r := _guard(user)):
        return r
    return templates.TemplateResponse(request, "request_new.html", {"user": user})


@router.post("/requests")
def request_create(
    request: Request,
    title: str = Form(...),
    type: str = Form("purchase"),
    description: str = Form(""),
    qty: float = Form(1),
    unit_price: float = Form(0),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if (r := _guard(user)):
        return r
    req = appr.create_request(
        session, type=RequestType(type), requester_id=user.id, title=title,
        description=description, lines=[{"description": description or title, "qty": qty, "unit_price": unit_price}],
    )
    appr.submit_request(session, req.id)
    return RedirectResponse("/requests", status_code=303)


@router.get("/approvals", response_class=HTMLResponse)
def approvals_inbox(request: Request, user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    pending = appr.pending_for_user(session, user.id)
    return templates.TemplateResponse(request, "approvals.html", {"user": user, "pending": pending})


@router.post("/approvals/{request_id}/approve")
def approve(request_id: int, user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    appr.approve(session, request_id, user.id)
    return RedirectResponse("/approvals", status_code=303)


@router.post("/approvals/{request_id}/reject")
def reject(request_id: int, comment: str = Form(""), user=Depends(get_current_user),
           session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    appr.reject(session, request_id, user.id, comment=comment)
    return RedirectResponse("/approvals", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    items = notify.list_for_user(session, user.id)
    notify.mark_all_read(session, user.id)
    return templates.TemplateResponse(request, "notifications.html", {"user": user, "items": items})


@router.get("/notifications/unread")
def notifications_unread(user=Depends(get_current_user), session: Session = Depends(get_session)):
    if not user:
        return {"unread": 0}
    return {"unread": notify.unread_count(session, user.id)}


@router.get("/notifications/stream")
async def notifications_stream(user=Depends(get_current_user)):
    """SSE: push the unread count periodically (each client opens its own session)."""
    if not user:
        return RedirectResponse("/login", status_code=303)
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
               user=Depends(get_current_user), session: Session = Depends(get_session)):
    if (r := _guard(user)):
        return r
    period = period or date.today().strftime("%Y-%m")
    fin = acct.generate_financials(session, period)
    return templates.TemplateResponse(request, "financials.html", {"user": user, "fin": fin, "period": period})
