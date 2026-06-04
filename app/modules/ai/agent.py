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
    "You are the ERP assistant for this company. You act ONLY through the tools "
    "listed below. You have NO internet access and NO external data — no tax "
    "tables, no GSA/government per-diem rates, no airfare or market prices, no "
    "shipping rates, no facts beyond what a tool returns.\n\n"
    "HARD RULES — this is a financial system, so fabrication is unacceptable:\n"
    "1. NEVER invent, estimate, or 'look up' numbers, prices, rates, per-diems, "
    "dates, or IDs. Every figure you state MUST come from a tool result you "
    "actually received in this conversation. If you don't have it, say you don't.\n"
    "2. If a request needs an action or data not covered by a tool below, say "
    "plainly that you cannot do it and why. Do NOT substitute a different tool "
    "(e.g. do not turn a travel/expense request into a purchase request).\n"
    "3. If required details are missing (amount, quantity, vendor, ...), ASK the "
    "user for them. Never create a record with guessed values.\n"
    "4. Never say something was approved/created/posted unless a tool result "
    "confirms it; report the exact identifiers the tool returned.\n"
    "5. Keep SYSTEM DATA exactly as stored — SKUs, account codes, document "
    "numbers (PO-2026-0001), statuses, and names are English identifiers; never "
    "translate or restyle them.\n\n"
    "Reply in the SAME language the user wrote in (Korean -> Korean, English -> "
    "English); default English. Be concise.\n\n"
    "The ONLY things you can do (your tools):\n{tools}"
)


def _tool_catalog(schemas: list[dict]) -> str:
    if not schemas:
        return "- (none available to you)"
    return "\n".join(
        f"- {s['function']['name']}: {s['function'].get('description', '').strip()}"
        for s in schemas
    )


def _arguments(call: dict) -> dict:
    args = call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        try:
            return json.loads(args or "{}")
        except json.JSONDecodeError:
            return {}
    return args or {}


def _language_directive(message: str) -> str:
    """Detect the user's language from their message and force the reply language
    (the system prompt alone isn't reliable — the model sometimes drifts)."""
    if any("가" <= ch <= "힣" for ch in message):  # Hangul syllables
        return "The user wrote in Korean. You MUST write your reply in Korean."
    return "The user wrote in English. You MUST write your reply in English."


def run(session: Session, user: User, message: str, *, history: list[dict] | None = None,
        max_iters: int | None = None, chat=None) -> dict:
    """Run one user turn. Returns {reply, tool_calls:[...]}.

    `history` = prior [{role, content}] turns of this conversation (memory).
    `chat` lets tests inject a fake LLM; production uses llm.chat (Ollama)."""
    chat = chat or llm.chat
    max_iters = max_iters or settings.ai_max_tool_iters
    tools = registry.schemas_for(user)
    messages = [
        {"role": "system", "content": _SYSTEM.format(tools=_tool_catalog(tools))},
        {"role": "system", "content": _language_directive(message)},
        *(history or []),
        {"role": "user", "content": message},
    ]
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
