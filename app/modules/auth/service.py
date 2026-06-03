"""auth.service — the ONLY public entry point for auth/permissions (ARCHITECTURE §2).

Other modules call these functions; they never touch auth.models directly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DataBoundary, Role, Scope, User, UserScope
from .permissions import ScopeGrant, can_access, require_access
from .security import hash_password, verify_password


def create_user(
    session: Session,
    *,
    name: str,
    email: str,
    password: str,
    role: Role = Role.EMPLOYEE,
) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=str(role),
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


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
    session.add(grant)
    user.scopes.append(grant)
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
    "get_grants",
    "can_access",
    "require_access",
]
