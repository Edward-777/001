"""contracts.service — public API for the commitments register."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ..documents.models import Document
from ..procurement.models import Vendor
from .models import Contract, ContractKind, ContractStatus

_BILLING = {"monthly", "quarterly", "annual", "one_time"}


def add_contract(
    session: Session,
    *,
    title: str,
    counterparty: str,
    kind: str = str(ContractKind.OTHER),
    start_date: date | None = None,
    end_date: date | None = None,
    auto_renew: bool = False,
    notice_days: int = 30,
    amount: float | None = None,
    billing: str | None = None,
    vendor_id: int | None = None,
    document_id: int | None = None,
    notes: str | None = None,
    created_by: int | None = None,
) -> Contract:
    if not (title or "").strip() or not (counterparty or "").strip():
        raise ValueError("title and counterparty are required")
    if kind not in {k.value for k in ContractKind}:
        raise ValueError(f"kind must be one of {[k.value for k in ContractKind]}")
    if start_date and end_date and end_date < start_date:
        raise ValueError("end_date is before start_date")
    if notice_days < 0:
        raise ValueError("notice_days must be >= 0")
    if amount is not None and float(amount) < 0:
        raise ValueError("amount must be >= 0")
    if billing is not None and billing not in _BILLING:
        raise ValueError(f"billing must be one of {sorted(_BILLING)}")
    if vendor_id is not None and session.get(Vendor, vendor_id) is None:
        raise ValueError("vendor not found")
    if document_id is not None and session.get(Document, document_id) is None:
        raise ValueError("document not found")
    c = Contract(title=title.strip(), counterparty=counterparty.strip(), kind=kind,
                 start_date=start_date, end_date=end_date, auto_renew=auto_renew,
                 notice_days=notice_days, amount=amount, billing=billing,
                 vendor_id=vendor_id, document_id=document_id, notes=notes)
    session.add(c)
    session.flush()
    audit.record(session, actor_user_id=created_by, action="create",
                 entity_type="contract", entity_id=c.id,
                 detail={"title": c.title, "end_date": str(end_date)})
    return c


def end_contract(session: Session, contract_id: int, *,
                 ended_by: int | None = None) -> Contract:
    c = session.get(Contract, contract_id)
    if c is None:
        raise ValueError("contract not found")
    if c.status != str(ContractStatus.ACTIVE):
        raise ValueError(f"contract is already '{c.status}'")
    c.status = str(ContractStatus.ENDED)
    session.flush()
    audit.record(session, actor_user_id=ended_by, action="update",
                 entity_type="contract", entity_id=c.id, detail={"status": "ended"})
    return c


def list_contracts(session: Session, *, include_ended: bool = False) -> list[Contract]:
    stmt = select(Contract).order_by(Contract.end_date.is_(None), Contract.end_date)
    if not include_ended:
        stmt = stmt.where(Contract.status == str(ContractStatus.ACTIVE))
    return list(session.scalars(stmt))


def days_left(contract: Contract, *, as_of: date | None = None) -> int | None:
    if contract.end_date is None:
        return None
    return (contract.end_date - (as_of or date.today())).days


def _renewal_row(c: Contract, as_of: date) -> dict:
    left = days_left(c, as_of=as_of)
    if c.auto_renew:
        action = (f"auto-renews on {c.end_date} — cancel before then if unwanted"
                  if left is not None and left >= 0
                  else f"auto-renewed on {c.end_date} — update end_date to the new term")
    else:
        action = (f"expires on {c.end_date} — renew or let it lapse"
                  if left is not None and left >= 0
                  else f"expired on {c.end_date} — renew, or end it in the register")
    return {"contract_id": c.id, "title": c.title, "counterparty": c.counterparty,
            "kind": c.kind, "end_date": str(c.end_date), "days_left": left,
            "auto_renew": c.auto_renew,
            "amount": (str(c.amount) if c.amount is not None else None),
            "billing": c.billing, "action": action}


def upcoming_renewals(session: Session, *, as_of: date | None = None,
                      within_days: int | None = None) -> list[dict]:
    """Active contracts inside their notice window (or past end), soonest first.
    `within_days` overrides each contract's own notice_days when given."""
    as_of = as_of or date.today()
    out = []
    for c in list_contracts(session):
        if c.end_date is None:
            continue
        window = within_days if within_days is not None else c.notice_days
        if as_of >= c.end_date - timedelta(days=window):
            out.append(_renewal_row(c, as_of))
    out.sort(key=lambda r: r["end_date"])
    return out
