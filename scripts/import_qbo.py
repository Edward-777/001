"""Import a real QuickBooks Online export (Account List + Journal) and REPLACE the
current data with it. Reconstructs the full ledger so BS/IS/TB/GL show the real
books. (Subledgers — AP/AR aging, inventory — are not rebuilt from a journal.)

Usage:  python -m scripts.import_qbo
        python -m scripts.import_qbo "C:\\path\\Account List.csv" "C:\\path\\journal entry.csv"
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.db import Base, SessionLocal, engine
from app.modules import (  # noqa: F401  register all tables
    accounting, ai, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting.ledger_models import JournalEntry, JournalLine
from app.modules.accounting.models import Account, AccountType
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role

DL = os.path.expanduser("~/Downloads")
ACCOUNTS_CSV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DL, "Account List.csv")
JOURNAL_CSV = sys.argv[2] if len(sys.argv) > 2 else os.path.join(DL, "journal entry.csv")

# QBO account Type -> our 5 categories
_TYPE_MAP = {
    "Bank": AccountType.ASSET, "Accounts receivable (A/R)": AccountType.ASSET,
    "Other Current Assets": AccountType.ASSET, "Fixed Assets": AccountType.ASSET,
    "Other Assets": AccountType.ASSET,
    "Accounts payable (A/P)": AccountType.LIABILITY, "Credit Card": AccountType.LIABILITY,
    "Other Current Liabilities": AccountType.LIABILITY, "Long Term Liabilities": AccountType.LIABILITY,
    "Equity": AccountType.EQUITY,
    "Income": AccountType.REVENUE, "Other Income": AccountType.REVENUE,
    "Cost of Goods Sold": AccountType.EXPENSE, "Expenses": AccountType.EXPENSE,
    "Other Expense": AccountType.EXPENSE,
}


def _num(x: str) -> Decimal:
    x = (x or "").replace(",", "").replace("$", "").strip()
    if not x:
        return Decimal("0")
    neg = x.startswith("(") and x.endswith(")")
    x = x.strip("()")
    v = Decimal(x)
    return -v if neg else v


def _read(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.reader(fh))


def _leaf_code(full_name: str) -> str:
    """Recover the account code from QBO 'Full name' when the account-number column
    is blank. Names are hierarchical ('78000 Taxes:78010 Taxes paid:Property tax');
    the deepest level may have no number, so scan right-to-left for the nearest
    numbered ancestor (here -> 78010), which rolls up correctly in the statements."""
    for seg in reversed((full_name or "").split(":")):
        tok = seg.strip().split(" ", 1)[0]
        if tok.isdigit():
            return tok
    return ""


def load_accounts(session) -> dict[str, int]:
    rows = _read(ACCOUNTS_CSV)
    hdr = next(r for r in rows if "Type" in r and "Full name" in r)
    h = {name: i for i, name in enumerate(hdr)}
    by_code: dict[str, int] = {}
    unmapped_types = set()
    start = rows.index(hdr) + 1
    for r in rows[start:]:
        if len(r) <= h["Type"] or not r[h["Account #"]].strip():
            continue
        code = r[h["Account #"]].strip()
        qtype = r[h["Type"]].strip()
        atype = _TYPE_MAP.get(qtype)
        if atype is None:
            unmapped_types.add(qtype)
            continue
        detail = r[h["Detail type"]].strip() if len(r) > h["Detail type"] else ""
        acct = Account(code=code, name=r[h["Full name"]].strip()[:120], type=str(atype),
                       subtype=("bank" if qtype == "Bank" else (detail or qtype).lower()[:40]))
        session.add(acct)
        by_code[code] = acct  # resolve id after flush
    session.flush()
    by_id = {code: a.id for code, a in by_code.items()}
    if unmapped_types:
        print("  ! unmapped account types (skipped):", unmapped_types)
    print(f"  loaded {len(by_id)} accounts")
    return by_id


def load_journal(session, code_to_id: dict[str, int], suspense_id: int) -> tuple[int, int]:
    rows = _read(JOURNAL_CSV)
    hdr = next(r for r in rows if "Transaction date" in r)
    h = {name: i for i, name in enumerate(hdr)}
    di, ai_, dr_i, cr_i, desc_i, fn_i = (h["Transaction date"], h["Distribution account number"],
                                         h["Debit"], h["Credit"], h["Description"], h["Full name"])

    posted = lines_total = skipped = suspensed = 0
    missing = set()
    cur: list[tuple[int, Decimal, Decimal, str]] = []
    cur_date: date | None = None
    now = datetime.now(timezone.utc)
    seq = 0
    batch: list[JournalEntry] = []

    def flush_entry():
        nonlocal posted, lines_total, skipped, seq
        if not cur:
            return
        seq += 1
        je = JournalEntry(je_no=f"JE-IMP-{seq:06d}", entry_date=cur_date or date.today(),
                          description="QBO import", source_type="manual", status="posted",
                          posted_at=now)
        je.lines = [JournalLine(account_id=aid, debit=d, credit=c, memo=m[:400] or None)
                    for aid, d, c, m in cur]
        batch.append(je)
        posted += 1
        lines_total += len(cur)

    for r in rows[rows.index(hdr) + 1:]:
        if not r or len(r) <= cr_i:
            continue
        if r[0].startswith("Total for"):
            flush_entry()
            cur, cur_date = [], None
            continue
        d = r[di].strip()
        if "/" in d:  # a posting line
            try:
                cur_date = datetime.strptime(d, "%m/%d/%Y").date()
            except ValueError:
                pass
            code = r[ai_].strip() or _leaf_code(r[fn_i] if len(r) > fn_i else "")
            aid = code_to_id.get(code)
            d, c = _num(r[dr_i]), _num(r[cr_i])
            if aid is None:
                if d == 0 and c == 0:
                    skipped += 1  # QBO $0 transaction-header artifact
                    continue
                missing.add(code or (r[fn_i][:30] if len(r) > fn_i else "(blank)"))
                aid = suspense_id  # deleted/unmapped account with real $ -> suspense
                suspensed += 1
            cur.append((aid, d, c, r[desc_i].strip()))
        if len(batch) >= 1000:
            session.add_all(batch)
            session.flush()
            batch.clear()
    flush_entry()
    session.add_all(batch)
    session.flush()
    if missing:
        print(f"  ! {suspensed} lines to deleted/unmapped accounts -> Import Suspense; "
              f"{skipped} $0 artifacts skipped. e.g.:", list(missing)[:6])
    print(f"  posted {posted} entries / {lines_total} lines")
    return posted, lines_total


def main() -> None:
    for p in (ACCOUNTS_CSV, JOURNAL_CSV):
        if not os.path.exists(p):
            print("MISSING FILE:", p)
            return

    print("Dropping current data and recreating schema...")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with SessionLocal() as s:
        auth_svc.create_user(s, name="Admin", email="admin@001.local", password="admin", role=Role.ADMIN)
        auth_svc.create_user(s, name="Accountant", email="cfo@001.local", password="cfo", role=Role.ACCOUNTANT)
        s.flush()
        print("Loading Account List...")
        code_to_id = load_accounts(s)
        suspense = Account(code="00000", name="Import Suspense (legacy/deleted accounts)",
                           type=str(AccountType.ASSET), subtype="suspense")
        s.add(suspense)
        s.flush()
        print("Loading Journal (this is 5.8MB / ~5,700 entries, give it a moment)...")
        load_journal(s, code_to_id, suspense.id)
        s.commit()

        from app.modules.accounting import service as acct
        p = acct.latest_active_period(s)
        tb = acct.trial_balance(s, as_of=date(int(p[:4]), int(p[5:7]), 28))
        bs = acct.balance_sheet(s, as_of=date(int(p[:4]), int(p[5:7]), 28))
        print(f"\nLatest period: {p}")
        print(f"Trial balance: debit {tb['total_debit']} / credit {tb['total_credit']} "
              f"balanced={tb['balanced']}")
        print(f"Balance sheet: assets {bs['total_assets']} = liab {bs['total_liabilities']} "
              f"+ equity {bs['total_equity']} (incl. net income {bs['net_income']}) "
              f"balanced={bs['balanced']}")
        print("\nLogin: admin@001.local / admin")


if __name__ == "__main__":
    main()
