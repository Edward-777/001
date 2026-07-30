"""M5 — approval workflow: org-chart routing, amount-band climb, approve/reject,
and the RequestApproved event (which M6 will consume to create POs)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.approval import service as appr
from app.modules.approval.events import RequestApproved
from app.modules.approval.models import RequestStatus, RequestType
from app.modules.auth import service as auth_svc
from app.modules.hr import service as hr_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        appr.seed_approval_rules(s)
        s.flush()
        yield s


@pytest.fixture
def org(session):
    """Staff -> Mgr -> Dir -> CEO, each with a linked user account."""
    people = {}
    parent = None
    for name in ["ceo", "dir", "mgr", "staff"]:
        u = auth_svc.create_user(session, name=name, email=f"{name}@001.local", password="pw")
        session.flush()
        e = hr_svc.create_employee(
            session, employee_no=name.upper(), name=name,
            reports_to_id=parent.id if parent else None, user_id=u.id,
        )
        people[name] = dict(user=u, emp=e)
        parent = e
    session.flush()
    return people


def test_small_purchase_routes_one_level(session, org):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="Buy widgets", lines=[{"description": "widget", "qty": 2, "unit_price": 100}],
    )
    assert req.total_amount == 200
    appr.submit_request(session, req.id)

    lines = appr._lines(session, req.id)
    # 0..1000 -> climb 1 -> only the Mgr
    assert [ln.approver_id for ln in lines] == [org["mgr"]["user"].id]
    assert req.status == RequestStatus.SUBMITTED


def test_large_purchase_climbs_higher(session, org):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="Big buy", lines=[{"description": "server", "qty": 1, "unit_price": 15000}],
    )
    appr.submit_request(session, req.id)
    lines = appr._lines(session, req.id)
    # >=10000 -> climb 3 -> Mgr, Dir, CEO
    assert [ln.approver_id for ln in lines] == [
        org["mgr"]["user"].id, org["dir"]["user"].id, org["ceo"]["user"].id
    ]


def test_full_approval_sequence_emits_event(session, org):
    # wire a local bus listener via the global bus
    from app.core.events import bus
    captured = []
    bus.subscribe(RequestApproved, lambda e, s: captured.append(e.request_id))
    try:
        req = appr.create_request(
            session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
            title="Mid buy", lines=[{"description": "x", "qty": 1, "unit_price": 5000}],
        )
        appr.submit_request(session, req.id)  # climb 2 -> Mgr, Dir

        # Mgr approves (step 1)
        appr.approve(session, req.id, org["mgr"]["user"].id)
        assert req.status == RequestStatus.SUBMITTED  # still awaiting Dir
        # Dir approves (step 2) -> fully approved
        appr.approve(session, req.id, org["dir"]["user"].id)
        assert req.status == RequestStatus.APPROVED
        assert captured == [req.id]
    finally:
        bus.clear()


def test_out_of_turn_approval_blocked(session, org):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="x", lines=[{"description": "x", "qty": 1, "unit_price": 5000}],
    )
    appr.submit_request(session, req.id)  # Mgr then Dir
    # Dir tries to approve before Mgr
    with pytest.raises(PermissionError):
        appr.approve(session, req.id, org["dir"]["user"].id)


def test_reject_terminates(session, org):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="x", lines=[{"description": "x", "qty": 1, "unit_price": 200}],
    )
    appr.submit_request(session, req.id)
    appr.reject(session, req.id, org["mgr"]["user"].id, comment="not needed")
    assert req.status == RequestStatus.REJECTED


def test_top_of_org_auto_approves(session, org):
    # CEO has no manager -> no approvers -> auto-approved
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["ceo"]["user"].id,
        title="ceo buy", lines=[{"description": "x", "qty": 1, "unit_price": 50}],
    )
    appr.submit_request(session, req.id)
    assert req.status == RequestStatus.APPROVED
    assert appr._lines(session, req.id) == []
