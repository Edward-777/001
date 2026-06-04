"""AI assistant chat (Phase 2). A logged-in user chats; the agent runs as that
user so tools obey their permissions. Conversations are persisted (2c) so the
agent has memory and chats are reviewable (own; admins audit all)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.ai import agent
from ..modules.ai import conversations as convo
from ..modules.ai import invoice as invoice_parser
from ..modules.documents import service as docs
from .deps import require_login, templates

router = APIRouter()
_UPLOAD_DIR = Path("uploads")


def _format_invoice(d: dict) -> str:
    lines = "\n".join(
        f"  • {(ln.get('description') or '')[:70]}  ×{ln.get('qty')} @ ${ln.get('unit_price')}"
        f" = ${ln.get('amount')}" for ln in (d.get("lines") or [])
    )
    return (
        "I read this invoice (local vision model — nothing left this machine):\n"
        f"Vendor: {d.get('vendor_name')}\n"
        f"Invoice #: {d.get('invoice_no')}   Date: {d.get('invoice_date')}\n"
        f"PO: {d.get('po_number')}   Currency: {d.get('currency')}\n"
        f"{lines}\n"
        f"Subtotal ${d.get('subtotal')}  Freight ${d.get('freight')}  "
        f"Tax ${d.get('tax')}  Total ${d.get('total')}\n\n"
        "Want me to record it as a vendor bill? If you've received the goods, give me "
        "the receipt (inbound) number and I'll 3-way match it."
    )


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, user=Depends(require_login),
                   session: Session = Depends(get_session)):
    conv = convo.get_or_create_active(session, user.id)
    msgs = convo.messages_of(session, conv.id)
    return templates.TemplateResponse(request, "assistant.html",
                                      {"user": user, "conversation": conv, "messages": msgs})


@router.post("/assistant/new")
def assistant_new(user=Depends(require_login), session: Session = Depends(get_session)):
    convo.start_new(session, user.id)
    return RedirectResponse("/assistant", status_code=303)


@router.post("/assistant/message", response_class=HTMLResponse)
def assistant_message(
    request: Request,
    message: str = Form(...),
    user=Depends(require_login),
    session: Session = Depends(get_session),
):
    conv = convo.get_or_create_active(session, user.id)
    history = convo.history_for_llm(session, conv.id)
    try:
        out = agent.run(session, user, message, history=history)
        reply, tools = out["reply"], [t["tool"] for t in out["tool_calls"]]
        error = None
    except Exception as exc:  # Ollama down, etc.
        reply, tools, error = "", [], f"Assistant unavailable: {type(exc).__name__}"

    if error is None:
        convo.add_message(session, conv, "user", message)
        convo.add_message(session, conv, "assistant", reply, tools=tools)
    return templates.TemplateResponse(
        request, "_chat_turn.html",
        {"message": message, "reply": reply, "tools": tools, "error": error},
    )


@router.post("/assistant/upload", response_class=HTMLResponse)
def assistant_upload(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_login),
    session: Session = Depends(get_session),
):
    """Upload an invoice → read it locally with the vision model → show the parsed
    fields in the chat and keep them in context for the agent to act on."""
    _UPLOAD_DIR.mkdir(exist_ok=True)
    dest = _UPLOAD_DIR / (file.filename or "upload.bin")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    conv = convo.get_or_create_active(session, user.id)
    note = f"[Uploaded invoice: {file.filename}]"
    try:
        data = invoice_parser.parse_invoice(str(dest))
        docs.store_document(session, file_path=str(dest), filename=file.filename,
                            mime=file.content_type, extracted_text=json.dumps(data))
        reply, error = _format_invoice(data), None
        convo.add_message(session, conv, "user", note)
        convo.add_message(session, conv, "assistant", reply)
    except Exception as exc:
        reply, error = "", f"Couldn't read that invoice: {type(exc).__name__}"
    return templates.TemplateResponse(
        request, "_chat_turn.html",
        {"message": note, "reply": reply, "tools": ["read_invoice"], "error": error},
    )


@router.get("/assistant/history", response_class=HTMLResponse)
def assistant_history(request: Request, user=Depends(require_login),
                      session: Session = Depends(get_session)):
    from ..modules.auth import service as auth
    convs = convo.list_conversations(session, user)
    names = {u: (auth.get_user(session, u).name if auth.get_user(session, u) else f"#{u}")
             for u in {c.user_id for c in convs}}
    return templates.TemplateResponse(request, "conversations.html",
                                      {"user": user, "conversations": convs, "names": names})


@router.get("/assistant/c/{conversation_id}", response_class=HTMLResponse)
def assistant_view(request: Request, conversation_id: int, user=Depends(require_login),
                   session: Session = Depends(get_session)):
    conv = convo.get_conversation(session, conversation_id, user)
    if conv is None:
        return RedirectResponse("/assistant/history", status_code=303)
    msgs = convo.messages_of(session, conv.id)
    owner_view = conv.user_id != user.id  # admin viewing someone else's
    return templates.TemplateResponse(request, "conversation_view.html",
                                      {"user": user, "conversation": conv,
                                       "messages": msgs, "owner_view": owner_view})
