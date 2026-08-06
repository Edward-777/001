"""AI Runtime Map (v2 roadmap): one page that shows how the AI runtime is
actually wired — inputs → local models → guardrails → human decision → system
of record, plus the memory/learning feedback loops. Every box is real code in
this repo and every number is queried live from the database, so the map
doubles as an ops dashboard: it never claims capability the system doesn't have.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from ..core.audit import AuditLog
from ..core.db import get_session
from ..modules.accounting.ledger_models import JournalEntry
from ..modules.ai.conversation_models import Conversation, UserMemory
from ..modules.ai.rag import RagChunk
from ..modules.ai.registry import registry
from ..modules.approval.models import Request as ApprovalRequest
from ..modules.approval.models import RequestStatus
from ..modules.documents.models import Document
from ..modules.fleet.models import Task, TaskStatus
from ..modules.learning.models import LearnedRule
from ..modules.mail.models import InboundEmail
from ..modules.payments.models import InstructionStatus, PaymentInstruction
from ..modules.policy.models import AutonomyPolicy, PolicyStatus
from .deps import require_login, templates

router = APIRouter()


def _count(session: Session, stmt) -> int:
    return session.scalar(stmt) or 0


def runtime_stats(session: Session) -> dict:
    """Live counts for the map. Aggregate numbers only — no record contents, so
    any logged-in user may see them (same visibility as the nav badges)."""
    n = lambda stmt: _count(session, stmt)  # noqa: E731
    count_of = lambda model, *where: n(  # noqa: E731
        select(func.count()).select_from(model).where(*where))

    tool_calls = count_of(AuditLog, AuditLog.action == "ai_tool")
    # detail_json is JSON in SQLite and JSONB in Postgres; a text LIKE on the
    # serialized form is the portable way to split ok/failed for a count.
    tool_fails = count_of(AuditLog, AuditLog.action == "ai_tool",
                          cast(AuditLog.detail_json, String).like('%"ok": false%'))

    role_tasks = dict(session.execute(
        select(Task.to_role, func.count()).group_by(Task.to_role)).all())

    return {
        # count what is actually callable today — feature-flagged (dormant)
        # tools don't belong on a live map
        "tools": sum(1 for t in registry._tools.values() if registry._enabled(t)),
        "tool_calls": tool_calls,
        "tool_fails": tool_fails,
        "conversations": count_of(Conversation),
        "memories": count_of(UserMemory),
        "documents": count_of(Document),
        "documents_indexed": count_of(Document, Document.is_indexed.is_(True)),
        "rag_chunks": count_of(RagChunk),
        "journal_entries": count_of(JournalEntry),
        "fleet_waiting": count_of(Task, Task.status == TaskStatus.NEEDS_APPROVAL),
        "fleet_done": count_of(Task, Task.status == TaskStatus.DONE),
        "role_tasks": role_tasks,
        "pending_approvals": count_of(
            ApprovalRequest, ApprovalRequest.status == RequestStatus.SUBMITTED),
        "rules_active": count_of(LearnedRule, LearnedRule.status == "active"),
        "rules_applied": n(select(func.coalesce(func.sum(LearnedRule.applied_count), 0))),
        "inbound_emails": count_of(InboundEmail),
        "policies_active": count_of(
            AutonomyPolicy, AutonomyPolicy.status == str(PolicyStatus.ACTIVE)),
        "payments_prepared": count_of(
            PaymentInstruction,
            PaymentInstruction.status == str(InstructionStatus.PREPARED)),
    }


@router.get("/map", response_class=HTMLResponse)
def runtime_map(request: Request, user=Depends(require_login),
                session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "runtime_map.html", {"user": user, "s": runtime_stats(session)})
