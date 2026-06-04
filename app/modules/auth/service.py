"""auth.service — the ONLY public entry point for auth/permissions (ARCHITECTURE §2).

Other modules call these functions; they never touch auth.models directly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DataBoundary, Role, Scope, User, UserScope
from .permissions import BoundaryResolver, Forbidden, ScopeGrant, can_access, require_access
from .security import hash_password, verify_password


# Default scope bundle per role (POLICIES §G11 -> DESIGN §8.5 axes).
_ROLE_SCOPES: dict[Role, list[tuple[Scope, int, DataBoundary]]] = {
    Role.ADMIN: [(s, 3, DataBoundary.ALL) for s in Scope],
    Role.ACCOUNTANT: [
        (Scope.FINANCE, 3, DataBoundary.ALL),
        (Scope.INVENTORY, 2, DataBoundary.ALL),
        (Scope.PROCUREMENT, 2, DataBoundary.ALL),
    ],
    Role.MANAGER: [
        (Scope.INVENTORY, 2, DataBoundary.DEPARTMENT),
        (Scope.PROCUREMENT, 2, DataBoundary.DEPARTMENT),
        (Scope.HR, 1, DataBoundary.TEAM),
        (Scope.FINANCE, 1, DataBoundary.SELF),
    ],
    Role.EMPLOYEE: [
        (Scope.HR, 1, DataBoundary.SELF),
        (Scope.FINANCE, 1, DataBoundary.SELF),
    ],
}

# A bcrypt hash of a throwaway value, used to keep authenticate() timing uniform
# whether or not the email exists (avoids a user-enumeration side channel).
_DUMMY_HASH = hash_password("timing-equalizer")


def apply_default_scopes(session: Session, user: User) -> None:
    """Grant the role's default scope bundle (idempotent via grant_scope)."""
    for scope, level, boundary in _ROLE_SCOPES.get(Role(user.role), []):
        grant_scope(session, user, scope, level, boundary)


def create_user(
    session: Session,
    *,
    name: str,
    email: str,
    password: str,
    role: Role = Role.EMPLOYEE,
    grant_defaults: bool = True,
) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=str(role),
    )
    session.add(user)
    session.flush()
    if grant_defaults:
        apply_default_scopes(session, user)
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        verify_password(password, _DUMMY_HASH)  # constant-time-ish: always hash
        return None
    return user if verify_password(password, user.password_hash) else None


def get_user(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def find_users_by_role(session: Session, role: str) -> list[User]:
    """Active users holding a role — used by fixed-role approval routing."""
    return list(
        session.scalars(select(User).where(User.role == str(role), User.is_active.is_(True)))
    )


def grant_scope(
    session: Session,
    user: User,
    scope: Scope,
    level: int,
    data_boundary: DataBoundary = DataBoundary.SELF,
) -> UserScope:
    """Grant/replace one (scope, level, boundary) for a user."""
    existing = next((s for s in user.scopes if s.scope == str(scope)), None)
    if existing:
        existing.level = level
        existing.data_boundary = str(data_boundary)
        return existing
    grant = UserScope(
        user_id=user.id, scope=str(scope), level=level, data_boundary=str(data_boundary)
    )
    user.scopes.append(grant)  # cascade persists it; no separate session.add needed
    return grant


def get_grants(user: User) -> dict[str, ScopeGrant]:
    """Materialize the user's scope grants for the permission gate."""
    return {
        s.scope: ScopeGrant(level=s.level, data_boundary=DataBoundary(s.data_boundary))
        for s in user.scopes
    }


def can_access_subject(session: Session, user: User, scope: str, level: int,
                       subject_employee_id: int | None) -> bool:
    """Full 3-axis check (scope × level × data_boundary) for a PER-SUBJECT record.

    The registry/UI gate only sees scope × level — the *subject* of a record is
    only known inside the handler. Any tool or query that returns one person's
    data (salary, review, per-employee document) MUST call this so the boundary
    (③) axis is enforced — otherwise a manager could read another team's data.
    """
    from ..hr import service as hr  # local import avoids an import-time cycle

    actor = hr.get_employee_by_user(session, user.id)
    return can_access(
        get_grants(user), scope, level,
        subject_employee_id=subject_employee_id,
        actor_employee_id=actor.id if actor else None,
        boundary_resolver=hr.make_boundary_resolver(session),
    )


# Re-export the gate so callers do `from auth.service import can_access, require_access`.
__all__ = [
    "create_user",
    "authenticate",
    "get_user",
    "find_users_by_role",
    "grant_scope",
    "apply_default_scopes",
    "get_grants",
    "can_access",
    "can_access_subject",
    "require_access",
    # public contract types (other modules import these from the service)
    "DataBoundary",
    "Role",
    "Scope",
    "BoundaryResolver",
    "ScopeGrant",
    "Forbidden",
]
