"""M6 — purchase orders, incl. the first event-driven integration:
approved purchase request --(RequestApproved)--> auto-created draft PO."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import approval, auth, hr, inventory, procurement  # noqa: F401
from app.modules.approval import service as appr
from app.modules.approval.models import RequestType
from app.modules.auth import service as auth_svc
from app.modules.hr import service as hr_svc
from app.modules.procurement import service as proc
from app.modules.procurement.handlers import register_handlers
from app.modules.procurement.models import POStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        appr.seed_approval_rules(s)
        register_handlers()  # opt in to procurement<-approval wiring for this test
        s.flush()
        yield s


@pytest.fixture
def org(session):
    people = {}
    parent = None
    for name in ["mgr", "staff"]:
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


def _approved_purchase(session, org, *, qty=2, price=100):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="Buy widgets",
        lines=[{"description": "widget", "qty": qty, "unit_price": price}],
    )
    appr.submit_request(session, req.id)            # climb 1 -> mgr
    appr.approve(session, req.id, org["mgr"]["user"].id)  # -> approved -> event -> PO
    return req


def test_approved_purchase_auto_creates_draft_po(session, org):
    req = _approved_purchase(session, org, qty=2, price=100)

    pos = proc.list_pos(session)
    assert len(pos) == 1
    po = pos[0]
    assert po.request_id == req.id
    assert po.status == POStatus.DRAFT
    assert po.vendor_id is None
    assert po.po_no.startswith("PO-")
    assert po.total == 200
    assert len(po.lines) == 1
    assert po.lines[0].qty_ordered == 2
    assert po.lines[0].unit_price == 100


def test_issue_po_assigns_vendor_and_opens(session, org):
    _approved_purchase(session, org)
    po = proc.list_pos(session)[0]
    vendor = proc.create_vendor(session, name="Acme")
    session.flush()

    proc.issue_po(session, po.id, vendor_id=vendor.id)
    assert po.status == POStatus.OPEN
    assert po.vendor_id == vendor.id
    assert po.order_date is not None


def test_cannot_issue_non_draft_po(session, org):
    _approved_purchase(session, org)
    po = proc.list_pos(session)[0]
    vendor = proc.create_vendor(session, name="Acme")
    session.flush()
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    with pytest.raises(ValueError, match="draft"):
        proc.issue_po(session, po.id, vendor_id=vendor.id)


def test_non_purchase_request_creates_no_po(session, org):
    req = appr.create_request(
        session, type=RequestType.EXPENSE, requester_id=org["staff"]["user"].id,
        title="Lunch", lines=[{"description": "lunch", "qty": 1, "unit_price": 50}],
    )
    appr.submit_request(session, req.id)
    appr.approve(session, req.id, org["mgr"]["user"].id)
    assert proc.list_pos(session) == []
