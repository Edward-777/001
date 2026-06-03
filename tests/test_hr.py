"""HR org chart: approval-chain walk + the boundary resolver that completes the
permission gate (DESIGN §8.5). Org used:

    CEO
     └ Dir (dept 10)
        └ Mgr  (dept 10)   <- 과장
           └ Staff (dept 10)
    OtherStaff (dept 20)   <- different department
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import auth, hr  # noqa: F401  register tables
from app.modules.auth.models import DataBoundary
from app.modules.auth.permissions import ScopeGrant, can_access
from app.modules.hr import service as hr_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def org(session):
    d10 = hr_svc.create_department(session, name="Sales")
    d20 = hr_svc.create_department(session, name="Eng")
    ceo = hr_svc.create_employee(session, employee_no="E1", name="CEO")
    dir_ = hr_svc.create_employee(
        session, employee_no="E2", name="Dir", department_id=d10.id, reports_to_id=ceo.id
    )
    mgr = hr_svc.create_employee(
        session, employee_no="E3", name="Mgr", department_id=d10.id, reports_to_id=dir_.id
    )
    staff = hr_svc.create_employee(
        session, employee_no="E4", name="Staff", department_id=d10.id, reports_to_id=mgr.id
    )
    other = hr_svc.create_employee(
        session, employee_no="E5", name="Other", department_id=d20.id, reports_to_id=ceo.id
    )
    session.flush()
    return dict(ceo=ceo, dir=dir_, mgr=mgr, staff=staff, other=other)


def test_manager_chain(session, org):
    chain = hr_svc.get_manager_chain(session, org["staff"].id)
    assert [e.name for e in chain] == ["Mgr", "Dir", "CEO"]


def test_approval_chain_levels(session, org):
    chain = hr_svc.get_approval_chain(session, org["staff"].id, levels=2)
    assert [e.name for e in chain] == ["Mgr", "Dir"]


def test_resolver_team_sees_reports(session, org):
    resolve = hr_svc.make_boundary_resolver(session)
    # Mgr's team includes Staff
    assert resolve(org["mgr"].id, org["staff"].id, DataBoundary.TEAM) is True
    # but Staff cannot see Mgr (upward) via team
    assert resolve(org["staff"].id, org["mgr"].id, DataBoundary.TEAM) is False


def test_resolver_department_vs_other_dept(session, org):
    resolve = hr_svc.make_boundary_resolver(session)
    # Dir (dept10) sees Staff (same dept) under department boundary
    assert resolve(org["dir"].id, org["staff"].id, DataBoundary.DEPARTMENT) is True
    # Dir cannot see Other (dept20) — different department, not a report
    assert resolve(org["dir"].id, org["other"].id, DataBoundary.DEPARTMENT) is False


def test_permission_gate_end_to_end_salary(session, org):
    """The canonical case, now wired through the real org chart."""
    resolve = hr_svc.make_boundary_resolver(session)

    # 부장(Dir): hr level 3, department boundary -> CAN see Staff's salary
    dir_grants = {"hr": ScopeGrant(level=3, data_boundary=DataBoundary.DEPARTMENT)}
    assert can_access(
        dir_grants, "hr", 3,
        subject_employee_id=org["staff"].id,
        actor_employee_id=org["dir"].id,
        boundary_resolver=resolve,
    ) is True

    # 과장(Mgr): hr level 2 -> CANNOT see salary (level), regardless of org chart
    mgr_grants = {"hr": ScopeGrant(level=2, data_boundary=DataBoundary.TEAM)}
    assert can_access(
        mgr_grants, "hr", 3,
        subject_employee_id=org["staff"].id,
        actor_employee_id=org["mgr"].id,
        boundary_resolver=resolve,
    ) is False

    # Dir cannot see Other-dept employee's salary (boundary)
    assert can_access(
        dir_grants, "hr", 3,
        subject_employee_id=org["other"].id,
        actor_employee_id=org["dir"].id,
        boundary_resolver=resolve,
    ) is False
