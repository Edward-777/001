"""Test isolation for the global event bus.

Handlers are registered on a process-global bus (app.core.events.bus). To keep
unit tests independent, clear it around every test; integration tests opt in by
registering the handlers they exercise.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_event_bus():
    from app.core.events import bus

    bus.clear()
    yield
    bus.clear()
