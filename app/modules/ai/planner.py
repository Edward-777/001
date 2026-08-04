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

# 'Create a purchase request ... and submit it for approval' — the second half
# is ALWAYS blocked by maker-checker (no draft is submitted in the turn that
# created it), and LLM plans for this message sent qwen into a vendor/PO tool
# spiral instead of create_purchase_request (live incident, 2026-08-04). One
# deterministic step, request-creation tools only; the compose step explains
# that submission waits for the human.
_PR_SUBMIT_RE = re.compile(
    r"(purchase\s+request|구매\s*(요청|신청)).{0,80}(submit|approval|승인|제출)"
    r"|(submit|제출).{0,80}(purchase\s+request|구매\s*(요청|신청))",
    re.IGNORECASE | re.DOTALL)

_PR_PLAN = [
    "Create the purchase request draft with the user's items, quantities and prices",
]

# Template steps come with a tool allowlist: the step is deterministic code, so
# the tools it may touch are too. Live incident (review test, 2026-08-04): given
# the full 65-tool surface inside a close plan, qwen2.5:14b wandered through
# ~27 calls and REGISTERED fabricated compliance obligations with 2023 dates —
# twice, despite 'USE ONLY when the user asked' in the tool description and
# 'NEVER create' in the step directive. Prompt levers don't hold under plan
# pressure; the allowlist removes the pen, not the instruction.
_STEP_TOOLS: dict[str, list[str]] = {
    _CLOSE_PLAN[0]: ["get_trial_balance"],
    _CLOSE_PLAN[1]: ["get_anomalies", "list_open_bills", "budget_vs_actual"],
    _CLOSE_PLAN[2]: ["generate_report"],
    # No submit tool on purpose: the draft is created, submission is the
    # human's move (maker-checker) — the model literally cannot jump the gate.
    _PR_PLAN[0]: ["create_purchase_request", "list_products", "get_stock",
                  "list_vendors"],
}


def tools_for_step(title: str) -> list[str] | None:
    """Allowlisted tool names for a template step; None = no restriction
    (LLM-planned steps keep the full permission-filtered surface)."""
    return _STEP_TOOLS.get(title)

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
    "- Each step must be a business action the system can execute directly "
    "(create the purchase request / approve X / record Y / report Z) and must "
    "carry the user's stated items, quantities and amounts verbatim.\n"
    "- Never plan paperwork: no 'draft a document', 'review for accuracy', "
    "'verify details' steps.\n"
    "Never invent work the user did not ask for. ONLY the JSON."
)


def _template_plan(message: str) -> list[str] | None:
    if _CLOSE_RE.search(message or ""):
        return list(_CLOSE_PLAN)
    if _PR_SUBMIT_RE.search(message or ""):
        return list(_PR_PLAN)
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
