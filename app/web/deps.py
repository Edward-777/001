"""Web layer shared deps: Jinja templates + session-cookie current user."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth.models import User

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return session.get(User, uid)
