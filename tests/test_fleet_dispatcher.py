"""Dispatcher routing (docs/AGENT-FLEET.md §3 mapping)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import fleet  # noqa: F401
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import service as q
from app.modules.fleet.models import Role, TaskSource, TaskStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_role_for_known_categories():
    assert disp.role_for("invoice") == Role.SPEND
    assert disp.role_for("receipt") == Role.SPEND
    assert disp.role_for("bank_statement") == Role.ACCOUNTING
    assert disp.role_for("contract") == Role.DOCS
    assert disp.role_for("customer_invoice") == Role.REVENUE


def test_unknown_category_is_held_by_dispatcher():
    assert disp.role_for("other") == Role.DISPATCHER
    assert disp.role_for("totally-made-up") == Role.DISPATCHER


def test_dispatch_enqueues_to_mapped_role(session):
    t = disp.dispatch(
        session, category="invoice", title="ACME bill",
        source=TaskSource.UPLOAD, payload={"total": 1200}, source_ref="doc:42",
    )
    assert t.to_role == Role.SPEND
    assert t.status == TaskStatus.QUEUED
    assert t.source_ref == "doc:42"
    assert q.next_queued(session, to_role=Role.SPEND).id == t.id


def test_dispatch_passes_through_idempotency(session):
    a = disp.dispatch(session, category="invoice", title="b",
                      source=TaskSource.UPLOAD, idempotency_key="doc-42:invoice")
    b = disp.dispatch(session, category="invoice", title="b2",
                      source=TaskSource.UPLOAD, idempotency_key="doc-42:invoice")
    assert a.id == b.id  # same upload classified twice -> one task
