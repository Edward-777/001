"""Web layer shared deps: Jinja templates + session-cookie auth/authz.

Authorization is enforced at the door here (P0-1): require_login covers
authentication; require_scope(scope, level) adds the 3-axis gate (DESIGN §8.5)
for sensitive pages. The same can_access predicate backs UI, AI, and RAG."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth import service as auth
from ..modules.auth.models import User

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return session.get(User, uid)


def _redirect_login() -> HTTPException:
    return HTTPException(status_code=303, headers={"Location": "/login"})


def require_login(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise _redirect_login()
    return user


def require_scope(scope: str, level: int):
    """Dependency factory: must be logged in AND hold `scope` at >= `level`."""

    def dep(user: User | None = Depends(get_current_user)) -> User:
        if user is None:
            raise _redirect_login()
        if not auth.can_access(auth.get_grants(user), scope, level):
            raise HTTPException(status_code=403, detail=f"Requires {scope} level {level}")
        return user

    return dep
