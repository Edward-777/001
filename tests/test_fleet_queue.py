"""Fleet work-queue state machine (docs/AGENT-FLEET.md §3)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import fleet  # noqa: F401  (register fleet_tasks)
from app.modules.fleet import service as q
from app.modules.fleet.models import Role, TaskSource, TaskStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _enqueue(session, **kw):
    defaults = dict(
        to_role=Role.SPEND, category="invoice", title="ACME bill",
        source=TaskSource.UPLOAD, payload={"total": 1200},
    )
    defaults.update(kw)
    return q.enqueue(session, **defaults)


def test_enqueue_creates_queued_task(session):
    t = _enqueue(session)
    assert t.id is not None
    assert t.status == TaskStatus.QUEUED
    assert t.to_role == Role.SPEND
    assert t.from_role == Role.DISPATCHER  # default
    assert t.payload == {"total": 1200}


def test_idempotency_key_dedupes(session):
    a = _enqueue(session, idempotency_key="inv-42")
    b = _enqueue(session, idempotency_key="inv-42", title="dup")
    assert a.id == b.id  # same row returned, not a second task
    assert q.list_tasks(session) == [a]


def test_next_queued_is_fifo_and_role_scoped(session):
    first = _enqueue(session, title="first")
    _enqueue(session, to_role=Role.REVENUE, title="revenue work")
    third = _enqueue(session, title="third")

    # oldest queued overall
    assert q.next_queued(session).id == first.id
    # scoped to a role skips other roles' work
    assert q.next_queued(session, to_role=Role.SPEND).id == first.id
    # after the first is claimed, spend's next is the third
    q.claim(session, first)
    assert q.next_queued(session, to_role=Role.SPEND).id == third.id


def test_claim_and_complete(session):
    t = _enqueue(session)
    q.claim(session, t)
    assert t.status == TaskStatus.IN_PROGRESS
    q.complete(session, t, result={"bill_no": "BILL-1"})
    assert t.status == TaskStatus.DONE
    assert t.result == {"bill_no": "BILL-1"}
    assert q.next_queued(session) is None  # nothing left queued


def test_request_approval_lands_in_inbox(session):
    t = _enqueue(session)
    q.claim(session, t)
    q.request_approval(session, t, approval_id=7, result={"draft_bill_id": 9})
    assert t.status == TaskStatus.NEEDS_APPROVAL
    assert t.approval_id == 7
    assert q.pending_approvals(session) == [t]


def test_resolve_approval_approved_and_rejected(session):
    a = _enqueue(session)
    q.request_approval(session, a)
    q.resolve_approval(session, a, approved=True)
    assert a.status == TaskStatus.DONE

    b = _enqueue(session)
    q.request_approval(session, b)
    q.resolve_approval(session, b, approved=False)
    assert b.status == TaskStatus.FAILED


def test_bounce_then_reroute(session):
    t = _enqueue(session, to_role=Role.PEOPLE)
    q.bounce(session, t, reason="not HR — looks like a vendor bill")
    assert t.status == TaskStatus.BOUNCED
    assert t.bounce_count == 1
    assert "vendor bill" in t.bounce_reason

    q.reroute(session, t, to_role=Role.SPEND)
    assert t.status == TaskStatus.QUEUED
    assert t.to_role == Role.SPEND
    assert t.from_role == Role.DISPATCHER


def test_bounce_escalates_after_limit(session):
    t = _enqueue(session)
    q.bounce(session, t, reason="r1")
    q.bounce(session, t, reason="r2")
    assert t.status == TaskStatus.BOUNCED
    q.bounce(session, t, reason="r3")  # 3rd bounce
    # ping-pong guard: escalate to the founder instead of bouncing forever
    assert t.bounce_count == 3
    assert t.status == TaskStatus.NEEDS_APPROVAL


def test_list_tasks_filters(session):
    a = _enqueue(session, title="spend")
    b = _enqueue(session, to_role=Role.REVENUE, title="revenue")
    q.claim(session, a)
    assert set(t.id for t in q.list_tasks(session)) == {a.id, b.id}
    assert q.list_tasks(session, status=TaskStatus.QUEUED) == [b]
    assert q.list_tasks(session, to_role=Role.REVENUE) == [b]
