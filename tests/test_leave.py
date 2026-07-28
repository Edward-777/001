"""Leave/PTO: balance math derived from approved requests, manager routing via
the org chart, decision authority, onboarding checklist — plus the AI tools and
the /leave page."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, documents, hr, leave, notifications  # noqa: F401
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Role, Scope
from app.modules.hr import service as hr_svc
from app.modules.leave import service as svc
from app.modules.leave.models import LeaveStatus
from app.modules.notifications.models import Notification


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def org(session):
    """boss (manager) <- worker, both with linked users."""
    boss_user = auth_svc.create_user(session, name="Boss", email="b@x", password="pw")
    worker_user = auth_svc.create_user(session, name="Worker", email="w@x", password="pw")
    boss = hr_svc.create_employee(session, employee_no="E1", name="Boss",
                                  user_id=boss_user.id)
    worker = hr_svc.create_employee(session, employee_no="E2", name="Worker",
                                    reports_to_id=boss.id, user_id=worker_user.id)
    return {"boss_user": boss_user, "worker_user": worker_user,
            "boss": boss, "worker": worker}


def test_business_days_excludes_weekends():
    # 2026-07-31 is a Friday; Mon 08-03 .. Tue 08-04
    assert svc.business_days(date(2026, 7, 31), date(2026, 8, 4)) == 3.0
    assert svc.business_days(date(2026, 8, 1), date(2026, 8, 2)) == 0.0  # Sat–Sun


def test_vacation_flow_routes_to_manager_and_updates_balance(session, org):
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=15)
    req = svc.request_leave(session, employee=org["worker"], kind="vacation",
                            start_date=date(2026, 8, 3), end_date=date(2026, 8, 5),
                            reason="family trip")
    assert req.status == str(LeaveStatus.PENDING)
    assert req.approver_employee_id == org["boss"].id
    assert req.days == 3.0
    # pending is reserved
    bal = svc.balance(session, org["worker"].id, 2026)
    assert (bal["granted"], bal["used"], bal["pending"], bal["available"]) == (15, 0, 3, 12)
    # the manager got notified
    notes = session.query(Notification).filter_by(user_id=org["boss_user"].id).all()
    assert any(n.type == "leave_request" for n in notes)

    svc.approve_leave(session, req.id, user=org["boss_user"], comment="enjoy")
    bal = svc.balance(session, org["worker"].id, 2026)
    assert (bal["used"], bal["pending"], bal["available"]) == (3, 0, 12)


def test_insufficient_balance_rejected_up_front(session, org):
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=2)
    with pytest.raises(ValueError, match="insufficient PTO"):
        svc.request_leave(session, employee=org["worker"], kind="vacation",
                          start_date=date(2026, 8, 3), end_date=date(2026, 8, 7))
    # sick leave is NOT balance-gated
    req = svc.request_leave(session, employee=org["worker"], kind="sick",
                            start_date=date(2026, 8, 3), end_date=date(2026, 8, 7))
    assert req.days == 5.0


def test_no_allowance_set_means_no_vacation(session, org):
    with pytest.raises(ValueError, match="no PTO allowance"):
        svc.request_leave(session, employee=org["worker"], kind="vacation",
                          start_date=date(2026, 8, 3), end_date=date(2026, 8, 3))


def test_overlap_rejected(session, org):
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=15)
    svc.request_leave(session, employee=org["worker"], kind="vacation",
                      start_date=date(2026, 8, 3), end_date=date(2026, 8, 5))
    with pytest.raises(ValueError, match="overlaps"):
        svc.request_leave(session, employee=org["worker"], kind="sick",
                          start_date=date(2026, 8, 5), end_date=date(2026, 8, 6))


def test_only_assigned_approver_or_admin_decides(session, org):
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=15)
    req = svc.request_leave(session, employee=org["worker"], kind="vacation",
                            start_date=date(2026, 8, 3), end_date=date(2026, 8, 3))
    # the requester cannot approve their own leave
    with pytest.raises(ValueError, match="only the assigned approver"):
        svc.approve_leave(session, req.id, user=org["worker_user"])
    # an admin can
    admin = auth_svc.create_user(session, name="Adm", email="a@x", password="pw",
                                 role=Role.ADMIN)
    out = svc.approve_leave(session, req.id, user=admin)
    assert out.status == str(LeaveStatus.APPROVED)


def test_top_of_org_chart_auto_approves(session, org):
    svc.set_allowance(session, employee_id=org["boss"].id, year=2026,
                      allowance_days=20)
    req = svc.request_leave(session, employee=org["boss"], kind="vacation",
                            start_date=date(2026, 8, 3), end_date=date(2026, 8, 3))
    assert req.status == str(LeaveStatus.APPROVED)
    assert "no manager" in req.decision_comment


def test_cancel_own_pending_only(session, org):
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=15)
    req = svc.request_leave(session, employee=org["worker"], kind="vacation",
                            start_date=date(2026, 8, 3), end_date=date(2026, 8, 3))
    with pytest.raises(ValueError, match="your own"):
        svc.cancel_leave(session, req.id, user=org["boss_user"])
    out = svc.cancel_leave(session, req.id, user=org["worker_user"])
    assert out.status == str(LeaveStatus.CANCELED)
    # canceled days are released
    assert svc.balance(session, org["worker"].id, 2026)["available"] == 15


def test_onboarding_checklist(session, org):
    tasks = svc.start_onboarding(session, employee=org["worker"])
    assert len(tasks) == 5
    assert svc.start_onboarding(session, employee=org["worker"]) == tasks  # idempotent
    svc.complete_onboarding_task(session, tasks[0].id)
    open_ = svc.open_onboarding(session)
    assert [(e.id, d, t) for e, d, t in open_] == [(org["worker"].id, 1, 5)]


# ---- AI tools ---------------------------------------------------------------

def test_ai_tools_request_and_approve_leave(session, org):
    from app.modules.ai.registry import registry
    svc.set_allowance(session, employee_id=org["worker"].id, year=2026,
                      allowance_days=15)
    out = registry.execute("request_time_off",
                           {"kind": "vacation", "start_date": "2026-08-03",
                            "end_date": "2026-08-05"},
                           session=session, user=org["worker_user"])["result"]
    assert out["status"] == "pending" and out["business_days"] == 3.0

    lst = registry.execute("list_leave_requests", {}, session=session,
                           user=org["boss_user"])["result"]
    assert len(lst["awaiting_my_approval"]) == 1
    leave_id = lst["awaiting_my_approval"][0]["leave_id"]

    ok = registry.execute("approve_leave", {"leave_id": leave_id},
                          session=session, user=org["boss_user"])["result"]
    assert ok["status"] == "approved"

    bal = registry.execute("get_pto_balance", {"year": 2026}, session=session,
                           user=org["worker_user"])["result"]
    assert bal["available"] == 12


def test_ai_tool_never_guesses_dates(session, org):
    from app.modules.ai.registry import registry
    out = registry.execute("request_time_off", {"start_date": "next week"},
                           session=session, user=org["worker_user"])["result"]
    assert "error" in out and "YYYY-MM-DD" in out["error"]


def test_hr_tools_gated_by_scope(session, org):
    from app.modules.ai.registry import registry
    out = registry.execute("set_pto_allowance",
                           {"employee_no": "E2", "allowance_days": 15},
                           session=session, user=org["worker_user"])
    assert "error" in out  # plain employee lacks hr L2
    hr_user = auth_svc.create_user(session, name="HR", email="h@x", password="pw")
    auth_svc.grant_scope(session, hr_user, Scope.HR, 2, DataBoundary.ALL)
    out = registry.execute("set_pto_allowance",
                           {"employee_no": "E2", "allowance_days": 15},
                           session=session, user=hr_user)["result"]
    assert out["allowance_days"] == 15.0
    ob = registry.execute("start_onboarding", {"employee_no": "E2"},
                          session=session, user=hr_user)["result"]
    assert len(ob["checklist"]) == 5
