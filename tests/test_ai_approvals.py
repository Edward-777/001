"""Chat approvals — approve/reject by request_no with comments, rich pending list.
The approver IS the checker, so these are single-turn tools; authority is enforced
by approval.service's current-approver guard, surfaced as error data by the registry."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, hr  # noqa: F401  register tables + tools
from app.modules.ai.registry import registry
from app.modules.approval import service as appr
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
    """staff -> mgr -> ceo, each with a user account."""
    people = {}
    parent = None
    for name in ["ceo", "mgr", "staff"]:
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


def _submit(session, org, *, title="Buy widgets", qty=2, price=100):
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title=title, lines=[{"description": title, "qty": qty, "unit_price": price}],
    )
    appr.submit_request(session, req.id)
    return req


def test_list_my_approvals_includes_requester_and_lines(session, org):
    _submit(session, org, title="Buy widgets", qty=2, price=100)
    out = registry.execute("list_my_approvals", {}, session=session,
                           user=org["mgr"]["user"])["result"]
    assert len(out) == 1
    row = out[0]
    assert row["requester"] == "staff"
    assert row["lines"][0]["description"] == "Buy widgets"
    assert row["lines"][0]["unit_price"].startswith("100")


def test_approve_by_request_no(session, org):
    req = _submit(session, org)
    out = registry.execute("approve_request", {"request_no": req.request_no},
                           session=session, user=org["mgr"]["user"])["result"]
    assert out["status"] == str(RequestStatus.APPROVED)


def test_reject_by_request_no_persists_comment(session, org):
    req = _submit(session, org)
    out = registry.execute("reject_request",
                           {"request_no": req.request_no, "comment": "over budget"},
                           session=session, user=org["mgr"]["user"])["result"]
    assert out["status"] == str(RequestStatus.REJECTED)
    line = appr.approval_lines(session, req.id)[0]
    assert line.comment == "over budget"


def test_wrong_turn_approver_gets_error_not_crash(session, org):
    req = _submit(session, org)
    out = registry.execute("approve_request", {"request_no": req.request_no},
                           session=session, user=org["ceo"]["user"])
    assert "not your turn" in out["error"]
    assert appr.get_request(session, req.id).status == str(RequestStatus.SUBMITTED)


def test_unknown_request_no_is_error_data(session, org):
    out = registry.execute("approve_request", {"request_no": "REQ-9999-9999"},
                           session=session, user=org["mgr"]["user"])["result"]
    assert "not found" in out["error"]
