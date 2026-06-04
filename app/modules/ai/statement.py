"""Bank statement parsing (local). PDF statements are read with the vision model;
CSV exports are parsed directly. Output feeds bank.import_and_reconcile."""
from __future__ import annotations

import csv
from pathlib import Path

from . import invoice, llm

_PROMPT = (
    "Extract this bank statement as ONLY a JSON object (no prose, no code fence):\n"
    '{"bank_name": str, "account_no": str, "period": "YYYY-MM", '
    '"opening_balance": number, "closing_balance": number, '
    '"lines": [{"txn_date": "YYYY-MM-DD", "description": str, "amount": number}]}\n'
    "amount is POSITIVE for deposits/credits and NEGATIVE for withdrawals/debits. "
    "Numbers must be plain (no commas, no currency symbols). Return ONLY the JSON."
)


def _parse_csv(path: str) -> dict:
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {"lines": []}
    header = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    di, desc_i, ai = col("date", "txn_date"), col("description", "memo", "details"), col("amount")
    lines = []
    for r in rows[1:]:
        if ai is None or ai >= len(r) or not r[ai].strip():
            continue
        amt = float(r[ai].replace(",", "").replace("$", "").strip())
        lines.append({
            "txn_date": (r[di].strip() if di is not None and di < len(r) else None),
            "description": (r[desc_i].strip() if desc_i is not None and desc_i < len(r) else ""),
            "amount": amt,
        })
    return {"bank_name": None, "account_no": None, "period": None,
            "opening_balance": 0, "closing_balance": 0, "lines": lines}


def parse_statement(path: str) -> dict:
    if Path(path).suffix.lower() == ".csv":
        return _parse_csv(path)
    return invoice._extract_json(llm.vision_chat(_PROMPT, invoice.load_images(path)))
