"""§8.4 document classification + bank statement parse/reconcile."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import accounting, ai, bank  # noqa: F401  register tables
from app.modules.accounting import service as acct
from app.modules.accounting.service import Line
from app.modules.ai import classify, llm, statement
from app.modules.bank import service as bank_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        s.flush()
        yield s


# ---- classification -----------------------------------------------------

def test_classify_maps_to_known_category(monkeypatch):
    monkeypatch.setattr(llm, "vision_chat", lambda p, imgs: "This is an INVOICE.")
    assert classify.classify([b"x"]) == "invoice"


def test_classify_unknown_falls_back_to_other(monkeypatch):
    monkeypatch.setattr(llm, "vision_chat", lambda p, imgs: "no idea what this is")
    assert classify.classify([b"x"]) == "other"


def test_routing_drives_acl_and_workflow():
    scope, level, route, index = classify.routing_for("invoice")
    assert (scope, level, route) == ("finance", 2, "ap_bill")
    # a policy is general-readable AND indexed; an invoice is finance-only, not indexed
    assert classify.routing_for("policy")[3] is True
    assert classify.routing_for("invoice")[3] is False


# ---- statement parsing + reconcile --------------------------------------

def test_parse_csv_statement(tmp_path):
    f = tmp_path / "stmt.csv"
    f.write_text("Date,Description,Amount\n2026-01-05,Customer deposit,100.00\n"
                 "2026-01-06,Rent ACH,-60.00\n", encoding="utf-8")
    parsed = statement.parse_statement(str(f))
    assert len(parsed["lines"]) == 2
    assert parsed["lines"][0]["amount"] == 100.0
    assert parsed["lines"][1]["amount"] == -60.0


def test_import_and_reconcile_matches_existing(session):
    cash = acct.get_account_by_role(session, "cash").id
    rev = acct.get_account_by_code(session, "4000").id
    acct.post_journal(session, entry_date=date(2026, 1, 5),
                      lines=[Line(cash, debit=100), Line(rev, credit=100)])
    bank_svc.create_bank_account(session, name="Checking", gl_account_id=cash)

    parsed = {"period": "2026-01", "opening_balance": 0, "closing_balance": 100,
              "lines": [{"txn_date": "2026-01-05", "description": "deposit", "amount": 100}]}
    r = bank_svc.import_and_reconcile(session, parsed)
    assert r["matched"] == 1
    assert r["unmatched"] == 0
    assert r["balance_ok"] is True


def test_reconcile_without_bank_account_errors(session):
    r = bank_svc.import_and_reconcile(session, {"lines": []})
    assert "error" in r
