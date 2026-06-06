"""Web layer shared deps: Jinja templates + session-cookie auth/authz.

Authorization is enforced at the door here (P0-1): require_login covers
authentication; require_scope(scope, level) adds the 3-axis gate (DESIGN §8.5)
for sensitive pages. The same can_access predicate backs UI, AI, and RAG."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth import service as auth
from ..modules.auth.models import User

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Turn report-download URLs in assistant text into real clickable links. The text
# comes from the LLM, so we FIRST html-escape everything (XSS guard) and only then
# linkify our own /reports/export endpoint — both the markdown form the model often
# writes ([label](url)) and a bare URL. This makes the download work everywhere the
# message is shown (live turn AND after a reload, where the green button is gone).
_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((/reports/export[^)\s]*)\)"   # 1=label, 2=url  (markdown link)
    r"|(/reports/export\?[^\s)\]<]*)"              # 3=bare url
)


def _linkify(text: str | None) -> Markup:
    if not text:
        return Markup("")
    safe = str(escape(text))  # escapes < > & " ' ; & becomes &amp; (valid in href)

    def repl(m: re.Match) -> str:
        href = m.group(2) or m.group(3)
        label = m.group(1)
        if not label or label.startswith("/reports/export"):
            label = "⬇ 리포트 다운로드 (.xlsx)"
        return (f'<a href="{href}" download '
                'class="text-emerald-700 font-medium underline '
                f'hover:text-emerald-900">{label}</a>')

    return Markup(_LINK_RE.sub(repl, safe))


templates.env.filters["linkify"] = _linkify


def _money(value) -> str:
    """Format a number/string/Decimal with thousands separators and 2 decimals
    (e.g. 38421954.22 -> '38,421,954.22') so amounts are quick to read."""
    from decimal import Decimal, InvalidOperation

    if value is None or value == "":
        return ""
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


templates.env.filters["money"] = _money


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
