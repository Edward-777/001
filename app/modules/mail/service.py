"""mail.service — ingest inbound email into the governed pipeline.

Provenance discipline (the email version of the injection defense):
- Email content is DATA. Nothing in a message body or attachment can execute;
  the most an email can do is create a DRAFT task a human approves.
- Attachment routing is stricter than upload routing on purpose: an upload was
  chosen by a logged-in human; an email is attacker-controllable input. So
  invoices/packing lists (draft-producing) dispatch normally, but bank
  statements and policy documents from email are HELD for a human — they are
  never auto-reconciled or auto-indexed into RAG from this surface.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.config import settings
from ..documents import service as docs
from ..fleet import dispatcher as fleet_dispatch
from ..fleet.models import TaskSource
from ..procurement.models import Vendor
from .models import InboundEmail, InboundStatus
from .provider import FilesystemMailbox, MailProvider, RawEmail

_UPLOAD_DIR = Path("uploads")
_ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".tsv",
                ".xlsx", ".xls", ".docx", ".txt", ".ofx", ".qbo"}

# categories that may dispatch straight to a role from EMAIL (draft-only flows);
# everything else classified is HELD for a human (default-deny by provenance)
_EMAIL_DISPATCHABLE = {"invoice", "packing_list", "receipt"}

_RE_PREFIX = re.compile(r"^\s*((re|fwd|fw)\s*:\s*)+", re.IGNORECASE)


def default_mailbox() -> FilesystemMailbox:
    return FilesystemMailbox(settings.mail_dir)


def thread_key(subject: str | None) -> str | None:
    if not subject:
        return None
    return _RE_PREFIX.sub("", subject).strip().lower()[:500] or None


def _match_vendor(session: Session, from_addr: str) -> Vendor | None:
    """Exact vendor-email match first; then unique domain match (a vendor whose
    stored email shares the sender's domain). Ambiguity means no match."""
    if not from_addr or "@" not in from_addr:
        return None
    exact = session.scalar(select(Vendor).where(Vendor.email == from_addr))
    if exact is not None:
        return exact
    domain = from_addr.split("@", 1)[1].lower()
    if domain in ("gmail.com", "outlook.com", "yahoo.com", "hotmail.com"):
        return None  # consumer domains identify a person, not a company
    matches = [v for v in session.scalars(
        select(Vendor).where(Vendor.email.is_not(None)))
        if (v.email or "").lower().endswith("@" + domain)]
    return matches[0] if len(matches) == 1 else None


def _save_attachment(filename: str, content: bytes) -> Path | None:
    """Attachment -> uploads dir. The client filename is never used as a path —
    only its (allowlisted) extension; the on-disk name is generated."""
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        return None
    _UPLOAD_DIR.mkdir(exist_ok=True)
    base = _UPLOAD_DIR.resolve()
    dest = (base / f"{uuid.uuid4().hex}{ext}").resolve()
    if not dest.is_relative_to(base):
        return None
    dest.write_bytes(content)
    return dest


def _process_attachment(session: Session, email_row: InboundEmail,
                        filename: str, dest: Path) -> tuple[str, object | None]:
    """Classify one saved attachment and route it. Returns (category, task)."""
    from ..ai import classify
    from ..ai import invoice as invoice_parser
    from ..ai import packing_list as packing_parser

    category = classify.classify_file(str(dest))
    acl_scope, acl_level, route, _ = classify.routing_for(category)
    doc = docs.store_document(session, file_path=str(dest), filename=filename,
                              mime=None, uploaded_by=None)
    doc.acl_scope, doc.acl_level, doc.classified_by = acl_scope, acl_level, "ai"

    sender = email_row.from_name or email_row.from_addr
    if category in _EMAIL_DISPATCHABLE and route == "ap_bill":
        import json

        data = invoice_parser.parse_invoice(str(dest))
        doc.extracted_text = json.dumps(data)
        task = fleet_dispatch.dispatch(
            session, category="invoice",
            title=f"{data.get('vendor_name') or sender} — ${data.get('total') or '?'}",
            source=TaskSource.EMAIL,
            payload={"parsed": data, "goods_received": None,
                     "email_id": email_row.id},
            source_ref=f"email:{email_row.id}",
            idempotency_key=f"email:{email_row.id}:doc:{doc.id}:invoice",
        )
        return category, task
    if category in _EMAIL_DISPATCHABLE and route == "supply":
        import json

        parsed = packing_parser.parse_packing_list(str(dest))
        doc.extracted_text = json.dumps(parsed)
        task = fleet_dispatch.dispatch(
            session, category="packing_list",
            title=f"{parsed.get('vendor_name') or sender} delivery — "
                  f"PO {parsed.get('po_number') or '?'}",
            source=TaskSource.EMAIL,
            payload={"parsed": parsed, "email_id": email_row.id},
            source_ref=f"email:{email_row.id}",
            idempotency_key=f"email:{email_row.id}:doc:{doc.id}:packing_list",
        )
        return category, task

    # default-deny by provenance: statements, policies, unknowns from email are
    # parked with the dispatcher — a human decides what they are
    task = fleet_dispatch.dispatch(
        session, category="email_review",
        title=f"Email attachment from {sender}: {filename} ({category})",
        source=TaskSource.EMAIL,
        payload={"doc_id": doc.id, "classified_as": category,
                 "email_id": email_row.id,
                 "note": "From email — held for review; never auto-processed."},
        source_ref=f"email:{email_row.id}",
        idempotency_key=f"email:{email_row.id}:doc:{doc.id}:review",
    )
    return category, task


def ingest(session: Session, raw: RawEmail) -> InboundEmail:
    """One email -> one provenance row (+ 0..n fleet tasks). Idempotent."""
    existing = session.scalar(select(InboundEmail).where(
        InboundEmail.message_id == raw.message_id))
    if existing is not None:
        return existing

    vendor = _match_vendor(session, raw.from_addr)
    row = InboundEmail(
        message_id=raw.message_id, from_addr=raw.from_addr,
        from_name=raw.from_name, to_addr=raw.to_addr,
        subject=(raw.subject or "")[:500] or None,
        body_text=raw.body_text, received_at=raw.received_at,
        thread_key=thread_key(raw.subject),
        vendor_id=vendor.id if vendor else None,
        attachment_count=len(raw.attachments),
    )
    session.add(row)
    session.flush()

    categories: list[str] = []
    task = None
    held = False
    for att in raw.attachments:
        dest = _save_attachment(att.filename, att.content)
        if dest is None:
            held = True
            categories.append("blocked_type")
            continue
        try:
            category, t = _process_attachment(session, row, att.filename, dest)
            categories.append(category)
            if t is not None:
                task = t
                if category not in _EMAIL_DISPATCHABLE:
                    held = True
        except Exception as exc:
            row.status = str(InboundStatus.FAILED)
            row.status_note = f"attachment failed: {type(exc).__name__}"
            session.flush()
            return row

    if task is not None:
        row.task_id = task.id
        row.status = str(InboundStatus.HELD if held else InboundStatus.DISPATCHED)
    else:
        row.status = str(InboundStatus.RECEIVED)
    row.category = ",".join(dict.fromkeys(categories)) or (
        "correspondence" if row.body_text else None)
    session.flush()
    audit.record(session, actor_user_id=None, action="ingest",
                 entity_type="inbound_email", entity_id=row.id,
                 detail={"from": row.from_addr, "status": row.status,
                         "category": row.category})
    return row


def poll_and_ingest(session: Session,
                    provider: MailProvider | None = None) -> list[InboundEmail]:
    provider = provider or default_mailbox()
    return [ingest(session, raw) for raw in provider.poll()]


def list_recent(session: Session, limit: int = 50) -> list[InboundEmail]:
    return list(session.scalars(
        select(InboundEmail).order_by(InboundEmail.id.desc()).limit(limit)))
