"""hr.service — public API for org chart, approval routing, and the
permission boundary resolver (ARCHITECTURE §2).

Boundary semantics (DESIGN §8.5 axis ③):
  TEAM       = the actor and everyone reporting (transitively) up to the actor.
  DEPARTMENT = TEAM, plus peers sharing the actor's department_id.
  (self / all are decided in auth.permissions; only team/department reach here.)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.service import BoundaryResolver, DataBoundary  # public contract
from .models import Department, Employee, EmployeeStatus

_MAX_DEPTH = 50  # cycle guard for malformed reports_to chains


# ---- writes -------------------------------------------------------------

def create_department(
    session: Session, *, name: str, parent_id: int | None = None
) -> Department:
    dept = Department(name=name, parent_id=parent_id)
    session.add(dept)
    session.flush()
    return dept


def create_employee(
    session: Session,
    *,
    employee_no: str,
    name: str,
    department_id: int | None = None,
    position_title: str | None = None,
    reports_to_id: int | None = None,
    hire_date: date | None = None,
    user_id: int | None = None,
) -> Employee:
    if reports_to_id is not None and session.get(Employee, reports_to_id) is None:
        raise ValueError("reports_to_id does not exist")
    emp = Employee(
        employee_no=employee_no,
        name=name,
        department_id=department_id,
        position_title=position_title,
        reports_to_id=reports_to_id,
        hire_date=hire_date,
        status=str(EmployeeStatus.ACTIVE),
        user_id=user_id,
    )
    session.add(emp)
    session.flush()
    return emp


def set_manager(session: Session, employee_id: int, reports_to_id: int | None) -> Employee:
    """Reassign an employee's manager, rejecting self-reference and cycles
    (a bad reporting line = an approval-routing + permission-boundary leak)."""
    emp = session.get(Employee, employee_id)
    if emp is None:
        raise ValueError("employee not found")
    if reports_to_id is not None:
        if reports_to_id == employee_id:
            raise ValueError("an employee cannot report to themselves")
        if session.get(Employee, reports_to_id) is None:
            raise ValueError("reports_to_id does not exist")
        # walking up from the proposed manager must not lead back to emp
        if any(m.id == employee_id for m in get_manager_chain(session, reports_to_id)):
            raise ValueError("reporting cycle detected")
    emp.reports_to_id = reports_to_id
    session.flush()
    return emp


# ---- reads / org-chart walks -------------------------------------------

def get_employee(session: Session, employee_id: int) -> Employee | None:
    return session.get(Employee, employee_id)


def get_employee_by_user(session: Session, user_id: int) -> Employee | None:
    return session.scalar(select(Employee).where(Employee.user_id == user_id))


def get_manager_chain(session: Session, employee_id: int) -> list[Employee]:
    """Managers from immediate up to the top (cycle-guarded)."""
    chain: list[Employee] = []
    seen: set[int] = set()
    current = session.get(Employee, employee_id)
    depth = 0
    while current and current.reports_to_id and depth < _MAX_DEPTH:
        if current.reports_to_id in seen:
            break
        seen.add(current.reports_to_id)
        manager = session.get(Employee, current.reports_to_id)
        if manager is None:
            break
        chain.append(manager)
        current = manager
        depth += 1
    return chain


def get_approval_chain(
    session: Session, employee_id: int, levels: int = 1
) -> list[Employee]:
    """The next `levels` approvers up the reporting line — used by M5 routing."""
    return get_manager_chain(session, employee_id)[:levels]


def _is_ancestor(session: Session, ancestor_id: int, employee_id: int) -> bool:
    """True if ancestor_id manages employee_id (directly or transitively)."""
    return any(m.id == ancestor_id for m in get_manager_chain(session, employee_id))


# ---- the boundary resolver for the permission gate (DESIGN §8.5) --------

def make_boundary_resolver(session: Session) -> BoundaryResolver:
    """Bind a resolver to a session so auth.can_access can decide team/department.
    Wiring this completes M1's fail-closed boundaries."""

    def resolver(actor_emp_id: int, subject_emp_id: int, boundary: DataBoundary) -> bool:
        if actor_emp_id is None or subject_emp_id is None:
            return False
        if subject_emp_id == actor_emp_id:
            return True
        # TEAM: subject reports up to actor.
        if _is_ancestor(session, actor_emp_id, subject_emp_id):
            return True
        if boundary == DataBoundary.DEPARTMENT:
            actor = session.get(Employee, actor_emp_id)
            subject = session.get(Employee, subject_emp_id)
            if (
                actor
                and subject
                and actor.department_id is not None
                and actor.department_id == subject.department_id
            ):
                return True
        return False

    return resolver
