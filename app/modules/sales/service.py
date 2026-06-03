"""sales.service — customer master (M3). Sales orders, AR invoices, receipts in M9."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Customer


def create_customer(
    session: Session,
    *,
    name: str,
    customer_no: str | None = None,
    payment_terms: str | None = None,
) -> Customer:
    c = Customer(name=name, customer_no=customer_no, payment_terms=payment_terms)
    session.add(c)
    session.flush()
    return c


def get_customer(session: Session, customer_id: int) -> Customer | None:
    return session.get(Customer, customer_id)


def list_customers(session: Session, *, active_only: bool = True) -> list[Customer]:
    stmt = select(Customer)
    if active_only:
        stmt = stmt.where(Customer.is_active.is_(True))
    return list(session.scalars(stmt))
