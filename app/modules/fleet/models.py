"""Fleet orchestration: the shared work queue (`tasks`) that role-agents pass
work through (docs/AGENT-FLEET.md §3).

One row = one unit of work. The dispatcher classifies an inbound item and
enqueues it for a `to_role`; the single work loop claims queued rows, processes
them as that role, and either completes, bounces (mis-routed), or parks the row
for the founder's approval. `idempotency_key` stops a re-running schedule from
enqueuing the same work twice.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class Role(StrEnum):
    """Who can own a task. Roles are configs (prompt+tools+permissions), not
    processes — the single loop 'wears' the to_role to process each task."""
    DISPATCHER = "dispatcher"   # 🧭 routing + founder chat interface
    REVENUE = "revenue"         # 💰 customer invoicing + collections (money in)
    SPEND = "spend"             # 💸 vendor bills + expenses (money out)
    ACCOUNTING = "accounting"   # 📒 auto-books, close, tax, reports
    INSIGHT = "insight"         # 📊 cash, burn, runway, anomaly alerts
    PEOPLE = "people"           # 👤 payroll, onboarding (optional)
    SUPPLY = "supply"           # 📦 inventory, PO, receiving (optional)
    DOCS = "docs"               # 📚 contracts, policy (optional)
    SUPPORT = "support"         # 🎧 customer inquiries (optional)
    CEO = "ceo"                 # 👔 the human founder
    SYSTEM = "system"           # the scheduler / framework itself


class TaskStatus(StrEnum):
    QUEUED = "queued"                  # waiting in the queue
    IN_PROGRESS = "in_progress"        # claimed by the work loop
    NEEDS_APPROVAL = "needs_approval"  # parked for the founder (posting/pay/send)
    BOUNCED = "bounced"                # mis-routed, awaiting re-route by dispatcher
    DONE = "done"
    FAILED = "failed"


class TaskSource(StrEnum):
    UPLOAD = "upload"        # a founder-uploaded document
    EMAIL = "email"          # pulled from the mailbox (phase 3)
    BANK_FEED = "bank_feed"  # a bank statement import
    CEO_CHAT = "ceo_chat"    # a conversational instruction
    AGENT = "agent"          # produced by another role (hand-off)


# bounce_count at/above this escalates to the founder instead of re-routing.
BOUNCE_ESCALATION_LIMIT = 3


class Task(PKMixin, TimestampMixin, Base):
    __tablename__ = "fleet_tasks"

    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    from_role: Mapped[str] = mapped_column(String(16), nullable=False)
    to_role: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=str(TaskStatus.QUEUED)
    )
    bounce_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bounce_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Loose reference to an approval Request (no FK — fleet stays decoupled).
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True, unique=True
    )
