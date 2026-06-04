"""Tool registry (AI-AGENT §2). A tool = a thin wrapper over a service function,
so the AI calls exactly what the human UI calls.

Permission inheritance (DESIGN §8.3, the carry-forward item): every tool carries
an optional required scope. The agent is only OFFERED the tools the current user
may use (defense layer 1), and execution RE-CHECKS the same predicate (layer 2).
So the AI can never exceed the caller's permissions — asking the AI for the GL is
denied for the same user the UI denies.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..auth import service as auth
from ..auth.models import User


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # JSON schema for the arguments
    handler: Callable[[Session, User, dict], object]
    scope: str | None = None  # required permission scope (None = any logged-in user)
    level: int = 1


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def _allowed(self, tool: Tool, user: User) -> bool:
        if tool.scope is None:
            return True
        return auth.can_access(auth.get_grants(user), tool.scope, tool.level)

    def schemas_for(self, user: User) -> list[dict]:
        """OpenAI tool schemas the user is allowed to use (permission-filtered)."""
        return [
            {"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in self._tools.values() if self._allowed(t, user)
        ]

    def execute(self, name: str, args: dict, *, session: Session, user: User) -> dict:
        """Run a tool as `user`. Re-checks permission (layer 2) and never raises —
        errors come back as data the model can read."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        if not self._allowed(tool, user):
            return {"error": f"permission denied: requires {tool.scope} level {tool.level}"}
        try:
            return {"result": tool.handler(session, user, args or {})}
        except Exception as exc:  # surface as data, not a crash
            return {"error": f"{type(exc).__name__}: {exc}"}

    def clear(self) -> None:
        self._tools.clear()


registry = Registry()
