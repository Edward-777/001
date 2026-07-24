"""procurement reacts to approval events (ARCHITECTURE §3).

When a PURCHASE request is fully approved, auto-create a draft PO from its line
snapshot. procurement never calls approval back — it only listens.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.events import bus
from ..approval.events import RequestApproved
from ..inventory.events import InboundPosted
from . import service


def on_request_approved(event: RequestApproved, session: Session) -> None:
    if event.request_type != "purchase":
        return
    po = service.create_po_from_request(
        session, request_id=event.request_id, lines=event.lines
    )
    # Tell the requester their spend is authorized and a draft PO awaits a vendor —
    # they know where they wanted to buy, and in a founder-run org they can act on it.
    from ..notifications import service as notify

    notify.notify(
        session, user_id=event.requester_id, type="po",
        title=f"Draft PO {po.po_no} created",
        body="Approved — tell the assistant which vendor to order from to issue it.",
        link=f"/requests/{event.request_id}",
    )


def on_inbound_posted(event: InboundPosted, session: Session) -> None:
    """A posted goods receipt against a PO rolls qty_received + the PO status
    (open → partially_received → received) — regardless of which surface received."""
    if not event.po_id:
        return
    receipts = [{"po_line_id": ln["po_line_id"], "qty": ln["qty"]}
                for ln in event.lines if ln.get("po_line_id")]
    if receipts:
        service.apply_receipt(session, po_id=event.po_id, receipts=receipts)


def register_handlers() -> None:
    bus.subscribe(RequestApproved, on_request_approved)
    bus.subscribe(InboundPosted, on_inbound_posted)
