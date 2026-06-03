"""Expense domain events — accounting books the expense and the reimbursement."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ...core.events import Event


@dataclass
class ExpenseApproved(Event):
    claim_id: int
    entry_date: date
    # [{expense_account_id, amount}] — debit these; credit Employee Payable total
    lines: list[dict] = field(default_factory=list)


@dataclass
class ReimbursementPosted(Event):
    reimbursement_id: int
    entry_date: date
    amount: Decimal
