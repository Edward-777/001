"""mail.models — inbound email as a first-class, auditable record.

Every email the system ingests gets one row: who sent it, what we matched it
to, how it was classified, and which fleet task (if any) it produced. The raw
source stays on disk; the row is the provenance chain.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class InboundStatus(StrEnum):
    RECEIVED = "received"        # parsed and stored, nothing actionable found
    DISPATCHED = "dispatched"    # produced at least one fleet task
    HELD = "held"                # default-deny: needs a human look (see service)
    FAILED = "failed"            # could not be parsed/processed


class OutboundStatus(StrEnum):
    DRAFT = "draft"                    # written (by AI or human), not sent
    SENT_SIMULATED = "sent_simulated"  # reference impl: written to outbox dir
    CANCELED = "canceled"


class OutboundEmail(PKMixin, TimestampMixin, Base):
    """Outbound mail is maker-checker end to end: anything (AI tools included)
    may DRAFT a message; only a human with finance authority sends it. The
    reference provider never leaves the machine (SENT_SIMULATED)."""
    __tablename__ = "outbound_emails"

    to_addr: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        default=str(OutboundStatus.DRAFT))
    # what business object this message is about (loose ref, like fleet tasks)
    related_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    related_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # threading: the inbound message this replies to
    reply_to_email_id: Mapped[int | None] = mapped_column(
        ForeignKey("inbound_emails.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                   nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                     nullable=True)
    # provider receipt (reference impl: the .eml path in the outbox dir)
    provider_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)


class InboundEmail(PKMixin, TimestampMixin, Base):
    __tablename__ = "inbound_emails"

    # RFC Message-ID — the idempotency key (a re-polled mailbox can't double-ingest)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    from_addr: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_addr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    # normalized subject (Re:/Fwd: stripped) — groups a conversation
    thread_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # sender matched against master data (provenance for everything downstream)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"),
                                                  nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(InboundStatus.RECEIVED))
    status_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # the fleet task this email produced (loose ref, like fleet.approval_id)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
