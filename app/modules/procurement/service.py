"""procurement.service — vendor master (M3). Purchase orders in M6."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PaymentTerms, Vendor


def create_vendor(
    session: Session,
    *,
    name: str,
    payment_terms: PaymentTerms = PaymentTerms.NET30,
    tax_id: str | None = None,
    is_1099: bool = False,
    email: str | None = None,
) -> Vendor:
    v = Vendor(
        name=name,
        payment_terms=str(payment_terms),
        tax_id=tax_id,
        is_1099=is_1099,
        email=email,
    )
    session.add(v)
    session.flush()
    return v


def get_vendor(session: Session, vendor_id: int) -> Vendor | None:
    return session.get(Vendor, vendor_id)


def list_vendors(session: Session, *, active_only: bool = True) -> list[Vendor]:
    stmt = select(Vendor)
    if active_only:
        stmt = stmt.where(Vendor.is_active.is_(True))
    return list(session.scalars(stmt))
