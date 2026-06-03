"""Gapless document numbering (POLICIES §G10): PREFIX-YYYY-NNNN, per type/year.

Allocated inside the caller's transaction with a row lock so numbers never gap
on rollback. Used by PO, JE, INV, EXP, ... (see POLICIES §G10 prefix list).
"""
from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import PKMixin
from .db import Base


class DocSequence(PKMixin, Base):
    __tablename__ = "doc_sequences"
    __table_args__ = (UniqueConstraint("doc_type", "year", name="uq_doc_seq"),)

    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def next_number(session: Session, doc_type: str, year: int) -> str:
    """Return the next gapless doc number, e.g. 'PO-2026-0001'.

    Locks the counter row (FOR UPDATE on Postgres) for the duration of the
    transaction. On SQLite (dev) the global write lock provides the same safety.
    The first allocation of a (type, year) races on the INSERT: two concurrent
    transactions both see no row and both insert. We resolve it with a savepoint —
    the loser catches the unique violation and re-selects the now-existing row
    with a lock (so numbering stays gapless).
    """
    def _locked_row():
        return (
            session.query(DocSequence)
            .filter_by(doc_type=doc_type, year=year)
            .with_for_update()
            .one_or_none()
        )

    row = _locked_row()
    if row is None:
        try:
            with session.begin_nested():  # savepoint
                row = DocSequence(doc_type=doc_type, year=year, last_no=0)
                session.add(row)
                session.flush()
        except IntegrityError:
            row = _locked_row()  # another txn created it first; take the lock
    row.last_no += 1
    return f"{doc_type}-{year}-{row.last_no:04d}"
