"""Mailroom — inbound email provenance and (phase 2) the outbox.

Viewing is login-gated; polling ingests untrusted input into the fleet, so it
sits behind the same finance L3 gate as the approval inbox actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.mail import service as mail
from .deps import require_login, require_scope, templates

router = APIRouter()
_finance = require_scope("finance", 3)


@router.get("/mail", response_class=HTMLResponse)
def mailroom(request: Request, user=Depends(require_login),
             session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "mail.html", {
        "user": user, "emails": mail.list_recent(session),
        "outbox": mail.list_outbox(session),
    })


@router.post("/mail/poll")
def mail_poll(user=Depends(_finance), session: Session = Depends(get_session)):
    mail.poll_and_ingest(session)
    return RedirectResponse("/mail", status_code=303)


@router.post("/mail/outbox/{outbound_id}/send")
def outbox_send(outbound_id: int, user=Depends(_finance),
                session: Session = Depends(get_session)):
    try:
        mail.send_outbound(session, outbound_id, user_id=user.id)
    except ValueError:
        pass  # stale click — the page re-render shows the real state
    return RedirectResponse("/mail", status_code=303)


@router.post("/mail/outbox/{outbound_id}/cancel")
def outbox_cancel(outbound_id: int, user=Depends(_finance),
                  session: Session = Depends(get_session)):
    try:
        mail.cancel_outbound(session, outbound_id, user_id=user.id)
    except ValueError:
        pass
    return RedirectResponse("/mail", status_code=303)
