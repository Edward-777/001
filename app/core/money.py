"""Shared money/quantity types and helpers (P2 — was redefined in ~10 modules).

Money/Qty are SQLAlchemy column types; money()/CENTS/ZERO are decimal helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Numeric

Money = Numeric(15, 2)
Qty = Numeric(15, 3)

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(x) -> Decimal:
    """Coerce to a 2-decimal money value (replaces the global `Decimal(str(x))` ritual)."""
    return Decimal(str(x)).quantize(CENTS)


def current_year() -> int:
    return datetime.now(timezone.utc).year
