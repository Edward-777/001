"""mail.provider — the mailbox boundary.

The public reference implementation ships a FILESYSTEM mailbox: drop .eml
files into `<mail_dir>/inbox/`, they are parsed and moved to `processed/`.
Real providers (IMAP/Gmail/SMTP) implement the same protocol in the private
deployment layer — the rest of the module never knows the difference.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass
class RawAttachment:
    filename: str
    content: bytes


@dataclass
class RawEmail:
    message_id: str
    from_addr: str
    from_name: str | None
    to_addr: str | None
    subject: str | None
    body_text: str | None
    received_at: datetime | None
    attachments: list[RawAttachment] = field(default_factory=list)


class MailProvider(Protocol):
    def poll(self) -> list[RawEmail]:
        """Fetch (and consume) new inbound messages."""
        ...


_ADDR_RE = re.compile(r"<([^>]+)>")


def _parse_addr(value: str | None) -> tuple[str, str | None]:
    """'Jane Doe <jane@acme.com>' -> ('jane@acme.com', 'Jane Doe')."""
    if not value:
        return "", None
    m = _ADDR_RE.search(value)
    if m:
        name = value[: m.start()].strip().strip('"') or None
        return m.group(1).strip().lower(), name
    return value.strip().lower(), None


def parse_eml(data: bytes) -> RawEmail:
    """Parse one RFC-822 message. Never trusts headers to be present."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    from_addr, from_name = _parse_addr(msg.get("From"))
    to_addr, _ = _parse_addr(msg.get("To"))
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        # content hash fallback keeps idempotency even for sloppy senders
        message_id = f"<sha256-{hashlib.sha256(data).hexdigest()}@local>"

    body_text = None
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        try:
            body_text = body.get_content()
        except Exception:
            body_text = None

    received_at = None
    if msg.get("Date"):
        try:
            received_at = email.utils.parsedate_to_datetime(msg["Date"])
        except Exception:
            received_at = None

    attachments = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "attachment.bin"
        try:
            content = part.get_content()
        except Exception:
            continue
        if isinstance(content, str):
            content = content.encode("utf-8", errors="replace")
        attachments.append(RawAttachment(filename=filename, content=content))

    return RawEmail(
        message_id=message_id, from_addr=from_addr, from_name=from_name,
        to_addr=to_addr, subject=msg.get("Subject"), body_text=body_text,
        received_at=received_at, attachments=attachments,
    )


class FilesystemMailbox:
    """The reference mailbox: `<root>/inbox/*.eml` in, `<root>/processed/` after.
    Also the outbound side used in later phases: sent mail is written to
    `<root>/outbox/` with a SENT_SIMULATED stamp — nothing leaves the machine."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.processed = self.root / "processed"
        self.outbox = self.root / "outbox"

    def ensure_dirs(self) -> None:
        for d in (self.inbox, self.processed, self.outbox):
            d.mkdir(parents=True, exist_ok=True)

    def poll(self) -> list[RawEmail]:
        self.ensure_dirs()
        out: list[RawEmail] = []
        for path in sorted(self.inbox.glob("*.eml")):
            try:
                out.append(parse_eml(path.read_bytes()))
            finally:
                # consumed either way — a poison message must not wedge the inbox
                path.rename(self.processed / path.name)
        return out

    def send(self, *, to_addr: str, subject: str, body_text: str,
             message_id: str) -> str:
        """Write the outbound message to disk. Returns the file path (the
        'provider receipt'). Real SMTP lives in the private layer."""
        self.ensure_dirs()
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", message_id)[:100]
        path = self.outbox / f"{safe_id}.eml"
        content = (f"Message-ID: {message_id}\nTo: {to_addr}\n"
                   f"Subject: {subject}\nX-001-Status: SENT_SIMULATED\n\n{body_text}")
        path.write_text(content, encoding="utf-8")
        return str(path)
