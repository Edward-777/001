"""policy.service — propose, activate, and evaluate autonomy envelopes.

Evaluation is pure code — no LLM anywhere in this module. Every condition is
deterministic, unknown condition keys FAIL CLOSED, and when nothing matches
the resolved level is L2 (today's behavior). Activation is human-only; the AI
may propose. The breaker suspends a policy after repeated human rejections of
its post-hoc review cards.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.money import money
from ..auth.models import User
from ..procurement.models import Vendor
from .models import (
    BREAKER_THRESHOLD,
    DEFAULT_LEVEL,
    AutonomyPolicy,
    PolicyDecision,
    PolicyStatus,
)

KNOWN_CONDITIONS = {"max_amount", "daily_cap", "vendor_allowlisted",
                    "account_codes", "budget_headroom"}
KNOWN_SCOPES = {"spend.approve_bill"}


# ---- lifecycle --------------------------------------------------------------

def propose_policy(session: Session, *, name: str, action_scope: str,
                   conditions: dict, max_level: int = 3,
                   effective_to: date | None = None,
                   proposed_by: int | None = None) -> AutonomyPolicy:
    if not (name or "").strip():
        raise ValueError("name is required")
    if action_scope not in KNOWN_SCOPES:
        raise ValueError(f"unknown action_scope {action_scope!r} — "
                         f"known: {sorted(KNOWN_SCOPES)}")
    if not 0 <= int(max_level) <= 4:
        raise ValueError("max_level must be 0..4")
    unknown = set(conditions or {}) - KNOWN_CONDITIONS
    if unknown:
        raise ValueError(f"unknown condition keys {sorted(unknown)} — "
                         f"known: {sorted(KNOWN_CONDITIONS)}")
    if not conditions:
        raise ValueError("an envelope with no conditions grants unbounded "
                         "autonomy — refused")
    # A spend envelope without a money bound is unbounded in the dimension that
    # matters most. Live incident (battery G3): asked to 'auto-approve Acme
    # invoices' with no limit stated, the model proposed vendor_allowlisted
    # alone — and this accepted it. Money bounds are now mandatory.
    if not any(k in conditions for k in ("max_amount", "daily_cap")):
        raise ValueError("a spend envelope needs a money bound — include "
                         "max_amount and/or daily_cap (ask the user for the "
                         "limit; never invent one)")
    for key in ("max_amount", "daily_cap"):
        if key in conditions and float(conditions[key]) <= 0:
            raise ValueError(f"{key} must be > 0")
    p = AutonomyPolicy(name=name.strip(), action_scope=action_scope,
                       max_level=int(max_level), conditions=conditions,
                       effective_to=effective_to, proposed_by=proposed_by)
    session.add(p)
    session.flush()
    audit.record(session, actor_user_id=proposed_by, action="create",
                 entity_type="autonomy_policy", entity_id=p.id,
                 detail={"scope": action_scope, "conditions": conditions})
    return p


def activate_policy(session: Session, policy_id: int, *, user: User) -> AutonomyPolicy:
    """Human-only. The route gates on finance L3; this records WHO signed."""
    p = session.get(AutonomyPolicy, policy_id)
    if p is None:
        raise ValueError("policy not found")
    if p.status not in (str(PolicyStatus.DRAFT), str(PolicyStatus.SUSPENDED)):
        raise ValueError(f"policy is '{p.status}' — only draft/suspended can activate")
    p.status = str(PolicyStatus.ACTIVE)
    p.approved_by = user.id
    p.approved_at = datetime.now(timezone.utc)
    p.suspend_reason = None
    p.rejection_count = 0
    session.flush()
    audit.record(session, actor_user_id=user.id, action="approve",
                 entity_type="autonomy_policy", entity_id=p.id,
                 detail={"status": "active"})
    return p


def suspend_policy(session: Session, policy_id: int, *, reason: str,
                   user_id: int | None = None) -> AutonomyPolicy:
    p = session.get(AutonomyPolicy, policy_id)
    if p is None:
        raise ValueError("policy not found")
    p.status = str(PolicyStatus.SUSPENDED)
    p.suspend_reason = reason[:400]
    session.flush()
    audit.record(session, actor_user_id=user_id, action="update",
                 entity_type="autonomy_policy", entity_id=p.id,
                 detail={"status": "suspended", "reason": reason})
    return p


def record_review_rejection(session: Session, policy_id: int,
                            *, user_id: int | None = None) -> AutonomyPolicy | None:
    """A human rejected an L3 post-hoc review card. Past the threshold the
    policy suspends itself — the tool-level failure breaker, lifted to policies."""
    p = session.get(AutonomyPolicy, policy_id)
    if p is None:
        return None
    p.rejection_count += 1
    session.flush()
    if (p.rejection_count >= BREAKER_THRESHOLD
            and p.status == str(PolicyStatus.ACTIVE)):
        suspend_policy(session, p.id, user_id=user_id,
                       reason=f"breaker: {p.rejection_count} review rejections")
    return p


def list_policies(session: Session) -> list[AutonomyPolicy]:
    return list(session.scalars(
        select(AutonomyPolicy).order_by(AutonomyPolicy.id.desc())))


def recent_decisions(session: Session, limit: int = 20) -> list[PolicyDecision]:
    return list(session.scalars(
        select(PolicyDecision).order_by(PolicyDecision.id.desc()).limit(limit)))


# ---- evaluation --------------------------------------------------------------

def _check(session: Session, policy: AutonomyPolicy, *, amount, vendor_id,
           account_code) -> dict:
    """Evaluate every condition of one policy. Returns {condition: bool|str}."""
    out: dict = {}
    conds = policy.conditions or {}
    for key, expected in conds.items():
        if key == "max_amount":
            out[key] = amount is not None and money(amount) <= money(expected)
        elif key == "daily_cap":
            # summed in Python for SQLite/PostgreSQL portability (JSON access
            # differs); L3 volumes are small by design, the envelope caps them
            rows = session.scalars(
                select(PolicyDecision).where(
                    PolicyDecision.policy_id == policy.id,
                    PolicyDecision.passed.is_(True))).all()
            today_iso = date.today().isoformat()
            # compare on the LOCAL business date stamped into the inputs
            # snapshot (timezone-proof and SQLite/PostgreSQL-portable)
            spent_today = sum(
                (money(r.inputs.get("amount") or 0) for r in rows
                 if r.inputs.get("date") == today_iso),
                Decimal("0"))
            out[key] = (amount is not None and
                        spent_today + money(amount) <= money(expected))
        elif key == "vendor_allowlisted":
            vendor = session.get(Vendor, vendor_id) if vendor_id else None
            out[key] = bool(vendor is not None
                            and vendor.autonomy_tier == "allowlisted")
        elif key == "account_codes":
            out[key] = account_code is not None and account_code in (expected or [])
        elif key == "budget_headroom":
            out[key] = _budget_headroom_ok(session, account_code, amount)
        else:
            out[key] = False  # unknown condition -> FAIL CLOSED
    return out


def _budget_headroom_ok(session: Session, account_code, amount) -> bool:
    """True only if the account HAS a budget and this amount stays inside it."""
    from ..accounting import service as acct
    from ..budget import service as budget_svc
    from ..budget.models import Budget

    if account_code is None or amount is None:
        return False
    account = acct.get_account_by_code(session, str(account_code))
    if account is None:
        return False
    today = date.today()
    row = session.scalar(select(Budget).where(
        Budget.account_id == account.id, Budget.year == today.year))
    if row is None:
        return False  # unbudgeted spend can never auto-execute
    spent = budget_svc.actual(session, account.id, today.year, today.month)
    return spent + money(amount) <= money(row.monthly_amount)


def evaluate(session: Session, *, action_scope: str, action_ref: str | None = None,
             amount=None, vendor_id: int | None = None,
             account_code: str | None = None) -> PolicyDecision:
    """Resolve the autonomy level for one action. Exactly one decision row is
    written per call — the audit-shaped 'why was this allowed / not allowed'."""
    today = date.today()
    candidates = list(session.scalars(
        select(AutonomyPolicy).where(
            AutonomyPolicy.action_scope == action_scope,
            AutonomyPolicy.status == str(PolicyStatus.ACTIVE))
        .order_by(AutonomyPolicy.id)))
    candidates = [p for p in candidates
                  if p.effective_to is None or p.effective_to >= today]

    inputs = {"amount": float(money(amount)) if amount is not None else None,
              "vendor_id": vendor_id, "account_code": account_code,
              "date": today.isoformat()}
    all_checks: dict = {}
    for p in candidates:
        checks = _check(session, p, amount=amount, vendor_id=vendor_id,
                        account_code=account_code)
        all_checks[f"policy:{p.id}:{p.name}"] = checks
        if checks and all(checks.values()):
            decision = PolicyDecision(
                policy_id=p.id, action_scope=action_scope, action_ref=action_ref,
                inputs=inputs, checks=all_checks, passed=True,
                resolved_level=p.max_level,
                # set client-side so same-session daily_cap sums see it
                created_at=datetime.now(timezone.utc))
            session.add(decision)
            session.flush()
            return decision

    decision = PolicyDecision(
        policy_id=None, action_scope=action_scope, action_ref=action_ref,
        inputs=inputs, checks=all_checks, passed=False,
        resolved_level=DEFAULT_LEVEL, created_at=datetime.now(timezone.utc))
    session.add(decision)
    session.flush()
    return decision
