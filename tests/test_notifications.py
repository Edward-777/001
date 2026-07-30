"""M14 — in-app notifications, including the approval-workflow integration."""
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
from app.modules.approval.models import RequestType
from app.modules.auth import service as auth_svc
from app.modules.hr import service as hr_svc
from app.modules.notifications import service as notify


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        appr.seed_approval_rules(s)
        s.flush()
        yield s


def test_notify_and_unread(session):
    u = auth_svc.create_user(session, name="u", email="u@x", password="pw")
    session.flush()
    notify.notify(session, user_id=u.id, type="approval", title="Hi")
    notify.notify(session, user_id=u.id, type="approval", title="There")
    assert notify.unread_count(session, u.id) == 2

    items = notify.list_for_user(session, u.id)
    notify.mark_read(session, items[0].id)
    assert notify.unread_count(session, u.id) == 1
    assert notify.mark_all_read(session, u.id) == 1
    assert notify.unread_count(session, u.id) == 0


@pytest.fixture
def org(session):
    people = {}
    parent = None
    for name in ["mgr", "staff"]:
        u = auth_svc.create_user(session, name=name, email=f"{name}@x", password="pw")
        session.flush()
        e = hr_svc.create_employee(session, employee_no=name.upper(), name=name,
                                   reports_to_id=parent.id if parent else None, user_id=u.id)
        people[name] = dict(user=u, emp=e)
        parent = e
    session.flush()
    return people


def test_submit_notifies_approver(session, org):
    req = appr.create_request(session, type=RequestType.PURCHASE,
                              requester_id=org["staff"]["user"].id, title="Buy",
                              lines=[{"qty": 1, "unit_price": 100}])
    appr.submit_request(session, req.id)
    # the manager (first approver) gets an "approval needed" notice
    mgr_notes = notify.list_for_user(session, org["mgr"]["user"].id)
    assert len(mgr_notes) == 1
    assert mgr_notes[0].type == "approval"
    assert "Buy" in mgr_notes[0].title


def test_decision_notifies_requester(session, org):
    req = appr.create_request(session, type=RequestType.PURCHASE,
                              requester_id=org["staff"]["user"].id, title="Buy",
                              lines=[{"qty": 1, "unit_price": 100}])
    appr.submit_request(session, req.id)
    appr.approve(session, req.id, org["mgr"]["user"].id)
    staff_notes = notify.list_for_user(session, org["staff"]["user"].id)
    assert any(n.title.startswith("Approved") for n in staff_notes)


def test_rejection_notifies_requester(session, org):
    req = appr.create_request(session, type=RequestType.PURCHASE,
                              requester_id=org["staff"]["user"].id, title="Buy",
                              lines=[{"qty": 1, "unit_price": 100}])
    appr.submit_request(session, req.id)
    appr.reject(session, req.id, org["mgr"]["user"].id, comment="no")
    staff_notes = notify.list_for_user(session, org["staff"]["user"].id)
    assert any(n.type == "rejection" for n in staff_notes)
