"""AI assistant chat (Phase 2). A logged-in user chats; the agent runs as that
user so tools obey their permissions. Conversations are persisted (2c) so the
agent has memory and chats are reviewable (own; admins audit all)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.ai import agent, classify, statement
from ..modules.ai import conversations as convo
from ..modules.ai import invoice as invoice_parser
from ..modules.ai import rag
from ..modules.bank import service as bank
from ..modules.documents import service as docs
from .deps import require_login, templates

router = APIRouter()
_UPLOAD_DIR = Path("uploads")
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
# Documents this ERP actually ingests (invoices, statements, policies, sheets).
_ALLOWED_UPLOAD_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".tsv",
    ".xlsx", ".xls", ".docx", ".txt", ".ofx", ".qbo",
}


def _safe_upload_dest(filename: str | None) -> Path:
    """Return a write path GUARANTEED to sit inside _UPLOAD_DIR.

    The client-supplied filename is never used as a path — we take only its
    extension (allowlisted) and generate the on-disk name — so '..\\..\\dev.db'
    or an absolute path cannot escape the uploads dir or clobber an existing file.
    The resolve()+is_relative_to() check is belt-and-suspenders."""
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXT:
        raise ValueError(f"file type not allowed: {ext or '(none)'}")
    base = _UPLOAD_DIR.resolve()
    dest = (base / f"{uuid.uuid4().hex}{ext}").resolve()
    if not dest.is_relative_to(base):
        raise ValueError("unsafe upload path")
    return dest


def _save_capped(src, dest: Path) -> None:
    """Stream an upload to disk, aborting past the size cap (no unbounded write)."""
    written = 0
    with dest.open("wb") as f:
        while chunk := src.read(1024 * 1024):
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise ValueError("file too large (max 25 MB)")
            f.write(chunk)


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
    download = None
    try:
        out = agent.run(session, user, message, history=history)
        reply, tools = out["reply"], [t["tool"] for t in out["tool_calls"]]
        # execution timeline: what ran, in order, how long, and whether it succeeded
        timeline = [{"tool": t["tool"], "ms": t.get("ms"), "ok": t.get("ok", True)}
                    for t in out["tool_calls"]]
        plan = out.get("plan")
        error = None
        # surface a report download link (if a tool produced one) as a button
        for t in out["tool_calls"]:
            res = (t.get("result") or {}).get("result")
            if isinstance(res, dict) and res.get("download_url"):
                download = res["download_url"]
                break
    except Exception as exc:  # Ollama down, etc.
        reply, tools, timeline, plan, error = "", [], [], None, \
            f"Assistant unavailable: {type(exc).__name__}"

    if error is None:
        convo.add_message(session, conv, "user", message)
        convo.add_message(session, conv, "assistant", reply, tools=tools)
    return templates.TemplateResponse(
        request, "_chat_turn.html",
        {"message": message, "reply": reply, "tools": tools, "timeline": timeline,
         "plan": plan, "error": error, "download": download},
    )


def _route_document(session, *, route, category, dest, doc, acl_scope, acl_level) -> str:
    """Act on a classified document (DESIGN §8.4): the category drives both the
    ACL (already set on doc) and the workflow it routes to."""
    header = f"📄 Detected: **{category}** (access: {acl_scope} L{acl_level}).\n\n"
    if route == "ap_bill":
        data = invoice_parser.parse_invoice(str(dest))
        doc.extracted_text = json.dumps(data)
        # Hand the parsed invoice to the fleet: the 💸 spend role will draft a bill
        # for the founder to approve (docs/AGENT-FLEET.md §9). Idempotent per doc.
        from ..modules.fleet import dispatcher as fleet_disp
        from ..modules.fleet.models import TaskSource
        fleet_disp.dispatch(
            session, category="invoice",
            title=f"{data.get('vendor_name') or 'Vendor'} — ${data.get('total') or '?'}",
            source=TaskSource.UPLOAD, payload={"parsed": data, "goods_received": None},
            source_ref=f"doc:{doc.id}", idempotency_key=f"doc:{doc.id}:invoice",
        )
        return header + _format_invoice(data) + (
            "\n\nI've drafted a vendor bill and placed it in your **Approval Inbox (/fleet)**.")
    if route == "reconcile":
        parsed = statement.parse_statement(str(dest))
        doc.extracted_text = json.dumps(parsed)
        r = bank.import_and_reconcile(session, parsed)
        if "error" in r:
            return header + r["error"]
        tie = "ties out ✅" if r["balance_ok"] else "does NOT tie out ⚠️"
        return header + (
            f"Imported {r['line_count']} lines for {r['bank']} ({r['period']}).\n"
            f"Auto-matched {r['matched']} to existing entries; {r['unmatched']} unmatched "
            f"(fees/interest — tell me how to categorize them). Statement balance {tie}."
        )
    if route == "supply":
        from ..modules.ai import packing_list as packing_parser
        from ..modules.fleet import dispatcher as fleet_disp
        from ..modules.fleet.models import TaskSource

        parsed = packing_parser.parse_packing_list(str(dest))
        doc.extracted_text = json.dumps(parsed)
        fleet_disp.dispatch(
            session, category="packing_list",
            title=(f"{parsed.get('vendor_name') or 'Supplier'} delivery — "
                   f"PO {parsed.get('po_number') or '?'}"),
            source=TaskSource.UPLOAD, payload={"parsed": parsed},
            source_ref=f"doc:{doc.id}", idempotency_key=f"doc:{doc.id}:packing_list",
        )
        lines = "\n".join(f"  • {ln.get('description')}  × {ln.get('qty')}"
                          for ln in (parsed.get("lines") or []))
        return header + (
            f"I read this packing list (local vision model):\n"
            f"Vendor: {parsed.get('vendor_name')}   PO: {parsed.get('po_number')}\n"
            f"{lines}\n\n"
            "I've drafted a goods receipt and placed it in your **Approval Inbox "
            "(/fleet)** — approving posts the stock and updates the PO."
        )
    if route == "rag":
        text = invoice_parser.extract_text(str(dest))
        if text.strip():
            n = rag.ingest(session, source=doc.filename or "document", text=text,
                           acl_scope=acl_scope, acl_level=acl_level)
            doc.is_indexed = True
            return header + f"Indexed into the knowledge base ({n} chunks) — ask me about it."
        return header + "Stored, but I couldn't extract text to index it."
    return header + (
        f"Stored for reference (doc #{doc.id}, not indexed). If this belongs to a "
        "vendor (e.g. a W-9), tell me which one and I'll attach it."
    )


@router.post("/assistant/upload", response_class=HTMLResponse)
def assistant_upload(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_login),
    session: Session = Depends(get_session),
):
    """Upload any document → classify it locally (§8.4) → ACL-tag + route: invoices
    are parsed, policies are indexed for RAG, statements are reconciled, else stored."""
    _UPLOAD_DIR.mkdir(exist_ok=True)
    conv = convo.get_or_create_active(session, user.id)
    note = f"[Uploaded: {file.filename}]"
    try:
        dest = _safe_upload_dest(file.filename)
        _save_capped(file.file, dest)
        category = classify.classify_file(str(dest))
        acl_scope, acl_level, route, _ = classify.routing_for(category)
        doc = docs.store_document(session, file_path=str(dest), filename=file.filename,
                                  mime=file.content_type, uploaded_by=user.id)
        doc.acl_scope, doc.acl_level, doc.classified_by = acl_scope, acl_level, "ai"
        reply = _route_document(session, route=route, category=category, dest=dest,
                                doc=doc, acl_scope=acl_scope, acl_level=acl_level)
        error = None
        convo.add_message(session, conv, "user", note)
        convo.add_message(session, conv, "assistant", reply)
    except ValueError as exc:  # rejected upload (type/size/unsafe path)
        reply, error = "", f"Upload rejected: {exc}"
    except Exception as exc:
        reply, error = "", f"Couldn't read that file: {type(exc).__name__}"
    return templates.TemplateResponse(
        request, "_chat_turn.html",
        {"message": note, "reply": reply, "tools": ["classify_document"], "error": error},
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
