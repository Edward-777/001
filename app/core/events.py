"""In-process domain event bus — the architectural centerpiece (ARCHITECTURE §3).

Synchronous, same-transaction dispatch:
  - A source module emits an event (e.g. InboundPosted) without knowing who listens.
  - Subscribers (e.g. accounting, assets) react within the SAME DB session/transaction,
    so the whole chain commits all-or-nothing. No Celery/Redis — keeps it lightweight
    while guaranteeing consistency.

Rule of thumb (ARCHITECTURE §3):
  - Need something / know the target  -> call its service directly (command/query).
  - Something happened / don't care who reacts -> emit an event (this module).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class Event:
    """Base class for all domain events. Subclass with a payload, e.g.:

    @dataclass
    class InboundPosted(Event):
        inbound_id: int
        lines: list[dict]   # {product_id, product_type, qty, unit_cost}
    """


Handler = Callable[[Event, Session], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    def emit(self, event: Event, session: Session) -> None:
        """Dispatch synchronously to every subscriber, in the caller's transaction.

        Handlers run inline; if any raises, it propagates so the caller's
        transaction rolls back (all-or-nothing).
        """
        for handler in self._subscribers[type(event)]:
            handler(event, session)

    def clear(self) -> None:
        """Test helper."""
        self._subscribers.clear()


# Global bus. Modules subscribe their handlers at import/registration time.
bus = EventBus()
