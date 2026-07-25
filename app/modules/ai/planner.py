"""ai.planner — plan-then-execute for multi-step requests (v2 roadmap P0-1).

Design:
- Known intents (e.g. month-end close) get a TEMPLATE plan — deterministic, the
  LLM only fills in execution. Everything else goes through one small planning
  call, gated by a cheap deterministic heuristic so single-question turns pay
  no extra latency.
- A plan is advisory decomposition, never authority: each step still executes
  through the same permission-checked tool loop, and the maker-checker gate
  spans the WHOLE user turn (a plan cannot create and submit in one turn).
- Planning failures degrade to the plain single-loop path — never to an error.
"""
from __future__ import annotations

import json
import re

from . import llm

MAX_STEPS = 5

# ---- template plans (deterministic for known intents) --------------------

_MONTHS = (r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|"
           r"sep(tember)?|oct(ober)?|nov(ember)?|dec(ember)?")
_CLOSE_RE = re.compile(
    rf"(close\s+(the\s+)?(books?|month|{_MONTHS})|month[- ]end close|closing package|"
    r"월\s*마감|마감\s*(해|진행|처리)|결산)", re.IGNORECASE)

_CLOSE_PLAN = [
    "Check the trial balance for the period",
    "Scan for spending anomalies and duplicate bills",
    "Generate the month-end closing package report",
]

# ---- LLM planning, deterministically gated --------------------------------

_MULTI_MARKERS = (" and ", " then ", ", ", " after ", "그리고", "하고", "한 다음",
                  "다음에", "→", ";")

_PLAN_PROMPT = (
    "You are the planning layer of a business operations assistant. Decide if the "
    "user's request needs MULTIPLE distinct actions executed in sequence.\n"
    'Reply with ONLY a JSON object: {"steps": [...]}.\n'
    "- A single question or single action -> {\"steps\": []}\n"
    "- A genuinely multi-action request -> 2 to 5 short imperative steps, written "
    "in the user's language, each step one concrete action.\n"
    "Never invent work the user did not ask for. ONLY the JSON."
)


def _template_plan(message: str) -> list[str] | None:
    if _CLOSE_RE.search(message or ""):
        return list(_CLOSE_PLAN)
    return None


def _worth_planning(message: str) -> bool:
    """Cheap gate: only spend a planning call when the message smells multi-step.
    Misses fall through to the plain loop, which is the status quo behavior."""
    msg = message or ""
    return len(msg) > 40 and any(m in msg for m in _MULTI_MARKERS)


def maybe_plan(message: str, *, chat=None) -> list[str] | None:
    """Return 2..MAX_STEPS step titles, or None for plain single-loop execution."""
    template = _template_plan(message)
    if template:
        return template
    if not _worth_planning(message):
        return None
    chat = chat or llm.chat
    try:
        msg = chat([{"role": "system", "content": _PLAN_PROMPT},
                    {"role": "user", "content": message}])
        content = msg.get("content", "") or ""
        i, j = content.find("{"), content.rfind("}")
        obj = json.loads(content[i:j + 1])
        steps = obj.get("steps")
        if (isinstance(steps, list) and 2 <= len(steps) <= MAX_STEPS
                and all(isinstance(s, str) and s.strip() for s in steps)):
            return [s.strip()[:200] for s in steps]
    except Exception:
        pass  # planning is best-effort; degrade to the plain loop
    return None
