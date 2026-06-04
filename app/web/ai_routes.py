"""AI assistant chat (Phase 2). A logged-in user chats; the agent runs as that
user so tools obey their permissions. HTMX posts a message and appends the turn."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.ai import agent
from .deps import require_login, templates

router = APIRouter()


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, user=Depends(require_login)):
    return templates.TemplateResponse(request, "assistant.html", {"user": user})


@router.post("/assistant/message", response_class=HTMLResponse)
def assistant_message(
    request: Request,
    message: str = Form(...),
    user=Depends(require_login),
    session: Session = Depends(get_session),
):
    try:
        out = agent.run(session, user, message)
        reply, tools = out["reply"], [t["tool"] for t in out["tool_calls"]]
        error = None
    except Exception as exc:  # Ollama down, etc.
        reply, tools, error = "", [], f"Assistant unavailable: {type(exc).__name__}"
    return templates.TemplateResponse(
        request, "_chat_turn.html",
        {"message": message, "reply": reply, "tools": tools, "error": error},
    )
