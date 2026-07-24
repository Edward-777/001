"""PO issuance via chat — the missing half of M6: a draft PO born from an approved
request can now be issued to a vendor, listed, documented (xlsx), and canceled."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, hr, notifications, procurement  # noqa: F401
from app.modules.ai.registry import registry
from app.modules.approval import service as appr
from app.modules.approval.models import RequestType
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Scope
from app.modules.hr import service as hr_svc
from app.modules.notifications.models import Notification
from app.modules.procurement import documents as pdocs
from app.modules.procurement import service as proc
from app.modules.procurement.handlers import register_handlers
from app.modules.procurement.models import POStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        appr.seed_approval_rules(s)
        register_handlers()
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
    auth_svc.grant_scope(session, people["mgr"]["user"], Scope.PROCUREMENT, 2, DataBoundary.ALL)
    session.flush()
    return people


def _approved_purchase(session, org, *, qty=2, price=100):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="Buy widgets",
        lines=[{"description": "widget", "qty": qty, "unit_price": price}],
    )
    appr.submit_request(session, req.id)
    appr.approve(session, req.id, org["mgr"]["user"].id)
    return req


def test_issue_po_by_request_no_returns_download_link(session, org):
    req = _approved_purchase(session, org)
    proc.create_vendor(session, name="Acme Supplies")
    out = registry.execute("issue_po",
                           {"request_no": req.request_no, "vendor": "Acme"},
                           session=session, user=org["mgr"]["user"])["result"]
    assert out["status"] == str(POStatus.OPEN)
    assert out["vendor"] == "Acme Supplies"
    assert out["download_url"].endswith("/document")


def test_issue_po_unknown_vendor_points_to_create_vendor(session, org):
    req = _approved_purchase(session, org)
    out = registry.execute("issue_po",
                           {"request_no": req.request_no, "vendor": "Nonexistent"},
                           session=session, user=org["mgr"]["user"])["result"]
    assert "create_vendor" in out["error"]
    assert proc.get_po_for_request(session, req.id).status == POStatus.DRAFT


def test_get_po_shows_ordered_vs_received(session, org):
    req = _approved_purchase(session, org, qty=3, price=50)
    out = registry.execute("get_po", {"request_no": req.request_no},
                           session=session, user=org["mgr"]["user"])["result"]
    assert out["lines"][0]["qty_ordered"].startswith("3")
    assert out["lines"][0]["qty_received"].startswith("0")
    assert "download_url" not in out  # drafts have no vendor document yet


def test_cancel_po_blocked_after_receipt(session, org):
    _approved_purchase(session, org)
    po = proc.list_pos(session)[0]
    po.lines[0].qty_received = 1
    session.flush()
    with pytest.raises(ValueError, match="received"):
        proc.cancel_po(session, po.id)


def test_build_po_xlsx(session, org):
    _approved_purchase(session, org)
    po = proc.list_pos(session)[0]
    vendor = proc.create_vendor(session, name="Acme Supplies", email="ap@acme.com")
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    filename, data = pdocs.build_po_xlsx(session, po.id)
    assert po.po_no in filename
    assert len(data) > 1000  # a real workbook, not an empty shell


def test_requester_notified_of_draft_po(session, org):
    _approved_purchase(session, org)
    po = proc.list_pos(session)[0]
    notes = session.scalars(
        select(Notification).where(Notification.user_id == org["staff"]["user"].id)
    ).all()
    assert any(po.po_no in (n.title or "") for n in notes)
