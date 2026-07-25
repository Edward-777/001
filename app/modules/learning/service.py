"""learning.service — governed learning: rules mined from human resolutions.

The loop: agents/humans resolve work → a deterministic miner finds the pattern →
the pattern is PROPOSED as a draft in the founder's approval inbox → approval
activates it → behavior changes on the very next occurrence → applied_count
records the payoff. No silent adaptation: every learned behavior is a row a
human approved and can revoke (ADR-10).

This module owns only the rule store + matching. Mining (which scans other
modules' data) lives with the fleet producers; application sites call the
resolve_* helpers here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LearnedRule

_LEGAL_SUFFIXES = ("inc", "incorporated", "llc", "ltd", "limited", "corp",
                   "corporation", "co", "company", "gmbh")


def normalize_vendor_name(name: str) -> str:
    """Canonical key for vendor-name matching: lowercase, punctuation stripped,
    legal suffixes dropped. 'Office Depot, Inc.' and 'OFFICE DEPOT' share a key."""
    text = re.sub(r"[^\w\s]", " ", (name or "").lower())
    words = [w for w in text.split() if w]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def create_rule(session: Session, *, kind: str, params: dict,
                evidence: str | None = None) -> LearnedRule:
    """Activate a learned rule — called from the APPROVAL side only (the proposal
    itself is a fleet task; rejecting it never creates a row here)."""
    rule = LearnedRule(kind=kind, params=params, evidence=(evidence or "")[:400],
                       status="active", approved_at=datetime.now(timezone.utc))
    session.add(rule)
    session.flush()
    return rule


def revoke_rule(session: Session, rule_id: int) -> LearnedRule:
    rule = session.get(LearnedRule, rule_id)
    if rule is None:
        raise ValueError("rule not found")
    rule.status = "revoked"
    session.flush()
    return rule


def active_rules(session: Session, kind: str | None = None) -> list[LearnedRule]:
    stmt = select(LearnedRule).where(LearnedRule.status == "active")
    if kind:
        stmt = stmt.where(LearnedRule.kind == kind)
    return list(session.scalars(stmt.order_by(LearnedRule.id)))


def resolve_vendor_alias(session: Session, name: str) -> int | None:
    """If an active vendor_alias rule covers this (normalized) name, return the
    canonical vendor id and count the application — the measurable behavior change."""
    key = normalize_vendor_name(name)
    if not key:
        return None
    for rule in active_rules(session, kind="vendor_alias"):
        if rule.params.get("alias_normalized") == key:
            rule.applied_count += 1
            session.flush()
            return rule.params.get("canonical_vendor_id")
    return None
