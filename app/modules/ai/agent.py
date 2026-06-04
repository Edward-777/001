"""The agent loop (AI-AGENT §3): natural language -> tool calls -> service ->
answer. Runs as the calling user, so every tool obeys that user's permissions.

The loop is bounded; tool results come back as data; the model never writes
journal entries as free text — it can only call the registered tools.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...core import audit
from ...core.config import settings
from ..auth.models import User
from . import llm
from .registry import registry

_SYSTEM = (
    "You are the ERP assistant for this company. Help the user with purchasing, "
    "approvals, inventory, and accounting by calling the available tools. Use tools "
    "for any company data — never guess numbers. If a request is outside company "
    "operations, politely say so. Be concise. "
    "Always reply in the same language the user wrote in; default to English."
)


def _arguments(call: dict) -> dict:
    args = call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        try:
            return json.loads(args or "{}")
        except json.JSONDecodeError:
            return {}
    return args or {}


def run(session: Session, user: User, message: str, *, max_iters: int | None = None,
        chat=None) -> dict:
    """Run one user turn. Returns {reply, tool_calls:[...]}.

    `chat` lets tests inject a fake LLM; production uses llm.chat (Ollama)."""
    chat = chat or llm.chat
    max_iters = max_iters or settings.ai_max_tool_iters
    tools = registry.schemas_for(user)
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": message}]
    used: list[dict] = []

    for _ in range(max_iters):
        msg = chat(messages, tools=tools)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"reply": msg.get("content", ""), "tool_calls": used}

        for call in calls:
            name = call.get("function", {}).get("name", "")
            args = _arguments(call)
            result = registry.execute(name, args, session=session, user=user)
            used.append({"tool": name, "args": args, "result": result})
            audit.record(session, actor_user_id=user.id, action="ai_tool",
                         entity_type=name, detail={"args": args, "ok": "error" not in result})
            messages.append({"role": "tool", "name": name, "content": json.dumps(result, default=str)})

    return {"reply": "(stopped: tool-iteration limit reached)", "tool_calls": used}
