"""auth.service — the ONLY public entry point for auth/permissions (ARCHITECTURE §2).

Other modules call these functions; they never touch auth.models directly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DataBoundary, Role, Scope, User, UserScope
from .permissions import ScopeGrant, can_access, require_access
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


# Re-export the gate so callers do `from auth.service import can_access, require_access`.
__all__ = [
    "create_user",
    "authenticate",
    "grant_scope",
    "apply_default_scopes",
    "get_grants",
    "can_access",
    "require_access",
]
