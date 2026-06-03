"""accounting.service — master-data slice for M3 (accounts, tax codes, COA seed).
Posting engine + journal entries arrive in M4.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .coa_seed import DEFAULT_COA
from .models import Account, AccountType, TaxCode


def create_account(
    session: Session,
    *,
    code: str,
    name: str,
    type: AccountType,
    subtype: str | None = None,
    system_role: str | None = None,
) -> Account:
    acct = Account(
        code=code, name=name, type=str(type), subtype=subtype, system_role=system_role
    )
    session.add(acct)
    session.flush()
    return acct


def get_account_by_code(session: Session, code: str) -> Account | None:
    return session.scalar(select(Account).where(Account.code == code))


def get_account_by_role(session: Session, role: str) -> Account | None:
    """Posting engine's primary lookup (M4): role -> account."""
    return session.scalar(select(Account).where(Account.system_role == role))


def find_journal_line_match(session: Session, *, account_id: int, amount, exclude_ids):
    """Find a posted journal line on `account_id` whose movement equals a bank
    statement line (M12). amount>0 = a debit (deposit); amount<0 = a credit
    (withdrawal). Skips lines already reconciled (exclude_ids)."""
    from decimal import Decimal as _D

    from .ledger_models import JournalLine

    amt = _D(str(amount))
    stmt = select(JournalLine).where(JournalLine.account_id == account_id)
    if exclude_ids:
        stmt = stmt.where(JournalLine.id.notin_(list(exclude_ids)))
    if amt > 0:
        stmt = stmt.where(JournalLine.debit == amt)
    else:
        stmt = stmt.where(JournalLine.credit == -amt)
    return session.scalars(stmt).first()


def seed_coa(session: Session) -> int:
    """Idempotently load the default Chart of Accounts. Returns # inserted."""
    existing = {c for (c,) in session.execute(select(Account.code)).all()}
    inserted = 0
    for code, name, type_, subtype, role in DEFAULT_COA:
        if code in existing:
            continue
        session.add(
            Account(code=code, name=name, type=str(type_), subtype=subtype, system_role=role)
        )
        inserted += 1
    session.flush()
    return inserted


def create_tax_code(
    session: Session, *, name: str, rate: Decimal | float = 0, tax_account_id: int | None = None
) -> TaxCode:
    tc = TaxCode(name=name, rate=Decimal(str(rate)), tax_account_id=tax_account_id)
    session.add(tc)
    session.flush()
    return tc


# ---- M4 posting engine (re-exported as the module's public API) ----------
from .posting import (  # noqa: E402
    Line,
    PostingError,
    apply_rule,
    close_period,
    ensure_period_open,
    get_or_create_period,
    post_journal,
    reverse_journal,
    seed_posting_rules,
)

__all__ = [
    "create_account",
    "get_account_by_code",
    "get_account_by_role",
    "seed_coa",
    "create_tax_code",
    # posting engine
    "Line",
    "PostingError",
    "post_journal",
    "apply_rule",
    "reverse_journal",
    "seed_posting_rules",
    "get_or_create_period",
    "ensure_period_open",
    "close_period",
    # AP (M10)
    "create_ap_bill",
    "match_ap_bill",
    "get_ap_bill",
    "create_payment",
]

# ---- M10 Accounts Payable (re-exported as public API) --------------------
from .ap import (  # noqa: E402
    create_ap_bill,
    create_payment,
    get_ap_bill,
    match_ap_bill,
)
