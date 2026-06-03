"""Event bus is the architectural centerpiece — prove it dispatches synchronously
within the caller's transaction (ARCHITECTURE §3)."""
from dataclasses import dataclass

from app.core.events import Event, EventBus


@dataclass
class InboundPosted(Event):
    inbound_id: int
    total_cost: float


def test_emit_calls_all_subscribers_in_order():
    bus = EventBus()
    calls: list[str] = []

    bus.subscribe(InboundPosted, lambda e, s: calls.append(f"accounting:{e.inbound_id}"))
    bus.subscribe(InboundPosted, lambda e, s: calls.append(f"assets:{e.inbound_id}"))

    bus.emit(InboundPosted(inbound_id=7, total_cost=100.0), session=None)

    assert calls == ["accounting:7", "assets:7"]


def test_handler_exception_propagates_for_rollback():
    """A failing handler must propagate so the caller's transaction rolls back
    (all-or-nothing): no partial posting."""
    bus = EventBus()

    def boom(event, session):
        raise ValueError("posting failed")

    bus.subscribe(InboundPosted, boom)

    try:
        bus.emit(InboundPosted(inbound_id=1, total_cost=1.0), session=None)
        assert False, "expected exception to propagate"
    except ValueError as exc:
        assert "posting failed" in str(exc)


def test_no_subscribers_is_noop():
    bus = EventBus()
    bus.emit(InboundPosted(inbound_id=1, total_cost=1.0), session=None)  # no raise
