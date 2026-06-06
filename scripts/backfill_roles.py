"""Backfill posting-engine anchors (system_role) onto an imported Chart of Accounts.

QBO imports bring account names/types but not 001's system_role anchors, which the
posting engine needs (e.g. post a vendor bill -> credit the 'ap' account). This
sets them by name match, idempotently. Run once after a QBO import.
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.accounting.models import Account

# role -> predicate on (lowercased name, account type). First match wins per role.
_BY_NAME = {
    "ap": lambda n, t: t == "liability" and "accounts payable" in n,
    "ar": lambda n, t: t == "asset" and "accounts receivable" in n,
    "revenue": lambda n, t: t == "revenue" and ("sales" in n or "revenue" in n or "income" in n),
    "retained_earnings": lambda n, t: t == "equity" and "retained earnings" in n,
}


def backfill(session) -> dict:
    accts = list(session.scalars(select(Account)))
    set_now = {}
    taken = {a.system_role for a in accts if a.system_role}

    for role, pred in _BY_NAME.items():
        if role in taken:
            continue
        for a in accts:
            if a.system_role:
                continue
            if pred((a.name or "").lower(), a.type):
                a.system_role = role
                set_now[role] = f"{a.code} {a.name}"
                taken.add(role)
                break

    # 'cash': the primary operating bank (a checking account, else first bank).
    if "cash" not in taken:
        banks = [a for a in accts if a.subtype == "bank" and not a.system_role]
        primary = next((a for a in banks if "checking" in (a.name or "").lower()), None) \
            or (banks[0] if banks else None)
        if primary is not None:
            primary.system_role = "cash"
            set_now["cash"] = f"{primary.code} {primary.name}"

    session.flush()
    return set_now


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    s = SessionLocal()
    result = backfill(s)
    s.commit()
    if result:
        print("Set anchors:")
        for role, acct in result.items():
            print(f"  {role:18} -> {acct}")
    else:
        print("Nothing to set (all anchors already present).")
