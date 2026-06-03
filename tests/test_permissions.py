"""The permission gate is the security spine (DESIGN §8.5). The canonical case:
an HR 과장 (level 2) must NOT see salary (hr level 3), even in the same dept."""
from app.modules.auth.models import DataBoundary
from app.modules.auth.permissions import ScopeGrant, Forbidden, can_access, require_access

SALARY_LEVEL = 3  # (hr, 3)


def grants(level, boundary=DataBoundary.DEPARTMENT):
    return {"hr": ScopeGrant(level=level, data_boundary=boundary)}


def test_manager_level2_cannot_see_salary():
    # 과장: hr level 2 -> blocked from (hr, 3)
    assert can_access(grants(2), "hr", SALARY_LEVEL) is False


def test_director_level3_can_see_salary_in_department():
    # 부장: hr level 3, boundary=department, subject in dept (resolver says yes)
    ok = can_access(
        grants(3, DataBoundary.DEPARTMENT),
        "hr",
        SALARY_LEVEL,
        subject_employee_id=42,
        actor_employee_id=1,
        boundary_resolver=lambda a, s, b: True,
    )
    assert ok is True


def test_director_cannot_see_other_department():
    # boundary=department, subject NOT in dept (resolver says no)
    ok = can_access(
        grants(3, DataBoundary.DEPARTMENT),
        "hr",
        SALARY_LEVEL,
        subject_employee_id=999,
        actor_employee_id=1,
        boundary_resolver=lambda a, s, b: False,
    )
    assert ok is False


def test_team_department_default_deny_without_resolver():
    # Fail-closed: no org-chart resolver wired yet -> deny (DESIGN §8.4)
    ok = can_access(
        grants(3, DataBoundary.TEAM),
        "hr",
        SALARY_LEVEL,
        subject_employee_id=42,
        actor_employee_id=1,
        boundary_resolver=None,
    )
    assert ok is False


def test_self_boundary_only_own_record():
    g = grants(3, DataBoundary.SELF)
    assert can_access(g, "hr", 3, subject_employee_id=7, actor_employee_id=7) is True
    assert can_access(g, "hr", 3, subject_employee_id=8, actor_employee_id=7) is False


def test_all_boundary_sees_any_subject():
    g = grants(3, DataBoundary.ALL)
    assert can_access(g, "hr", 3, subject_employee_id=8, actor_employee_id=7) is True


def test_no_scope_grant_denied():
    assert can_access({}, "finance", 1) is False


def test_non_subject_record_scope_level_enough():
    # generate_financials needs (finance, 3) but no per-person subject
    g = {"finance": ScopeGrant(level=3, data_boundary=DataBoundary.SELF)}
    assert can_access(g, "finance", 3) is True


def test_require_access_raises_forbidden():
    try:
        require_access(grants(2), "hr", SALARY_LEVEL)
        assert False, "expected Forbidden"
    except Forbidden:
        pass
