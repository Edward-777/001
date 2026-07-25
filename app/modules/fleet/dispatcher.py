"""fleet.dispatcher — the 🧭 router (docs/AGENT-FLEET.md §3).

Takes a classified inbound item and enqueues it for the right role. Pure
routing: classification already happened (ai/classify on upload, or the caller
for chat). An unknown/ambiguous category is held by the dispatcher itself so a
human can look — never silently dropped (default-deny).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import service as q
from .models import Role, Task, TaskSource

# category -> owning role (AGENT-FLEET §3 mapping). Categories beyond the current
# 6-way classifier are listed too; they simply never arrive until the classifier
# is extended (phases 2-4), so listing them now is harmless and forward-compatible.
ROLE_FOR_CATEGORY: dict[str, Role] = {
    "invoice": Role.SPEND,            # vendor bill -> money out
    "receipt": Role.SPEND,            # expense receipt
    "bank_statement": Role.ACCOUNTING,
    "policy": Role.DOCS,
    "contract": Role.DOCS,
    "customer_invoice": Role.REVENUE,  # money in (phase 2)
    "po_request": Role.SUPPLY,         # phase 4
    "goods_receipt": Role.SUPPLY,
    "packing_list": Role.SUPPLY,       # supplier delivery -> draft goods receipt
    "hr_doc": Role.PEOPLE,
    "customer_email": Role.SUPPORT,    # phase 3
}


def role_for(category: str) -> Role:
    """Owning role for a category; unknown -> the dispatcher holds it for review."""
    return ROLE_FOR_CATEGORY.get(category, Role.DISPATCHER)


def dispatch(
    session: Session,
    *,
    category: str,
    title: str,
    source: TaskSource | str,
    payload: dict | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> Task:
    """Route a classified item to its role's queue. Returns the enqueued Task."""
    return q.enqueue(
        session,
        to_role=role_for(category),
        category=category,
        title=title,
        source=source,
        payload=payload,
        from_role=Role.DISPATCHER,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
    )
