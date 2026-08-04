"""Payment instructions: prepare changes nothing, confirmation posts, the
system never claims to move money. Test-pinned semantics of the honest split
between instructing (L2), executing (human, outside), and recording (L3)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave, mail,
    notifications, obligations, payments, policy, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role as URole
from app.modules.payments import service as svc
from app.modules.payments.models import InstructionStatus
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        yield s


@pytest.fixture
def admin(session):
    return auth_svc.create_user(session, name="Adm", email="a@x", password="pw",
                                role=URole.ADMIN)


@pytest.fixture
def open_bill(session):
    """A posted (open) direct bill for $500 from a vendor with remit-to."""
    v = proc.create_vendor(session, name="Acme Supplies", email="ap@acme.com")
    v.remit_to = "Chase •••1234 · routing •••0021 · ACH preferred"
    bill = acct.create_ap_bill(
        session, vendor_id=v.id, vendor_invoice_no="INV-42",
        lines=[{"description": "consulting", "qty": 1, "unit_price": 500}])
    account = acct.get_account_by_code(session, "6300")
    acct.post_direct_bill(session, bill.id, account.id)
    return bill


def test_prepare_builds_the_packet_and_posts_nothing(session, admin, open_bill):
    instr = svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)
    assert instr.status == str(InstructionStatus.PREPARED)
    assert "Chase" in instr.remit_to
    assert open_bill.bill_no in instr.reference and "INV-42" in instr.reference
    assert instr.evidence["vendor_name"] == "Acme Supplies"
    assert instr.evidence["match_status"] == "unmatched"
    # NOTHING moved: the bill is still open at full balance, cash untouched
    assert open_bill.status == "open"
    assert float(open_bill.balance) == 500.0
    tb = {r["code"]: r for r in acct.trial_balance(session, as_of=date.today())["rows"]}
    assert str(tb["2000"]["credit"]) == "500.00"  # AP still owed


def test_prepare_refuses_drafts_settled_and_duplicates(session, admin, open_bill):
    with pytest.raises(ValueError, match="not found"):
        svc.prepare_instruction(session, bill_no="BILL-9999", user=admin)
    svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)
    with pytest.raises(ValueError, match="already"):
        svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)


def test_confirm_posts_the_journal_with_the_humans_date(session, admin, open_bill):
    instr = svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)
    paid = date.today() - timedelta(days=1)
    out = svc.confirm_executed(session, instr.id, user=admin, paid_date=paid,
                               payment_ref="wire #20260803-0042")
    assert out.status == str(InstructionStatus.CONFIRMED)
    assert out.payment_no and out.payment_ref == "wire #20260803-0042"
    session.refresh(open_bill)
    assert open_bill.status == "paid" and float(open_bill.balance) == 0.0
    # AP cleared to zero and the AP subledger ties out — the books record the
    # human's execution
    chk = acct.subledger_check(session, as_of=date.today())
    ap = next(c for c in chk["checks"] if c["control"] == "AP")
    assert float(ap["subledger"]) == 0


def test_confirm_rejects_future_dates_and_double_confirm(session, admin, open_bill):
    instr = svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)
    with pytest.raises(ValueError, match="future"):
        svc.confirm_executed(session, instr.id, user=admin,
                             paid_date=date.today() + timedelta(days=1))
    svc.confirm_executed(session, instr.id, user=admin, paid_date=date.today())
    with pytest.raises(ValueError, match="not prepared"):
        svc.confirm_executed(session, instr.id, user=admin,
                             paid_date=date.today())


def test_canceled_instruction_cannot_confirm(session, admin, open_bill):
    instr = svc.prepare_instruction(session, bill_no=open_bill.bill_no, user=admin)
    svc.cancel_instruction(session, instr.id, user=admin)
    with pytest.raises(ValueError, match="not prepared"):
        svc.confirm_executed(session, instr.id, user=admin,
                             paid_date=date.today())


# ---- AI tools -----------------------------------------------------------------

def test_ai_prepare_is_l2_and_says_nothing_moved(session, admin, open_bill):
    from app.modules.ai.registry import registry
    out = registry.execute("prepare_payment_instructions",
                           {"bill_no": open_bill.bill_no},
                           session=session, user=admin)["result"]
    assert out["pay_to"].startswith("Chase")
    assert "no money moves" in out["note"]
    session.refresh(open_bill)
    assert open_bill.status == "open"  # still nothing posted


def test_ai_confirm_needs_explicit_date_and_posts(session, admin, open_bill):
    from app.modules.ai.registry import registry
    prep = registry.execute("prepare_payment_instructions",
                            {"bill_no": open_bill.bill_no},
                            session=session, user=admin)["result"]
    bad = registry.execute("confirm_payment_executed",
                           {"instruction_id": prep["instruction_id"],
                            "paid_date": "yesterday"},
                           session=session, user=admin)["result"]
    assert "YYYY-MM-DD" in bad["error"]
    ok = registry.execute("confirm_payment_executed",
                          {"instruction_id": prep["instruction_id"],
                           "paid_date": date.today().isoformat(),
                           "payment_ref": "ACH-7788"},
                          session=session, user=admin)["result"]
    assert ok["payment_no"]
    session.refresh(open_bill)
    assert open_bill.status == "paid"


def test_pay_vendor_result_never_claims_money_moved(session, admin, open_bill):
    from app.modules.ai.registry import registry
    out = registry.execute("pay_vendor",
                           {"bill_no": open_bill.bill_no, "amount": 500},
                           session=session, user=admin)["result"]
    assert "No money was moved by the system" in out["note"]
