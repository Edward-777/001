"""procurement reacts to approval events (ARCHITECTURE §3).

When a PURCHASE request is fully approved, auto-create a draft PO from its line
snapshot. procurement never calls approval back — it only listens.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.events import bus
from ..approval.events import RequestApproved
from . import service


def on_request_approved(event: RequestApproved, session: Session) -> None:
    if event.request_type != "purchase":
        return
    service.create_po_from_request(
        session, request_id=event.request_id, lines=event.lines
    )


def register_handlers() -> None:
    bus.subscribe(RequestApproved, on_request_approved)
