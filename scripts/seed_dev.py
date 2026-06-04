"""Seed a runnable dev database: COA, rules, an org, and some live data so the
assistant has things to report.

Usage:  python -m scripts.seed_dev
Logins:
  admin@001.local / admin   (ADMIN — full access incl. financials)
  alice@001.local / alice   (EMPLOYEE — submits requests that route to admin)
"""
from datetime import date

from app.core.db import Base, SessionLocal, engine
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.approval import service as appr
from app.modules.approval.models import RequestType
from app.modules.auth import service as auth_svc
from app.modules.bank import service as bank_svc
from app.modules.auth.models import Role
from app.modules.hr import service as hr_svc
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc
from app.modules.sales import service as sls


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if auth_svc.authenticate(s, "admin@001.local", "admin"):
            print("Already seeded.")
            return
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        appr.seed_approval_rules(s)

        # admin = real ADMIN at the top of the org; alice reports to admin.
        admin = auth_svc.create_user(s, name="Admin", email="admin@001.local",
                                     password="admin", role=Role.ADMIN)
        alice = auth_svc.create_user(s, name="Alice", email="alice@001.local",
                                     password="alice", role=Role.EMPLOYEE)
        s.flush()
        admin_e = hr_svc.create_employee(s, employee_no="E1", name="Admin", user_id=admin.id)
        hr_svc.create_employee(s, employee_no="E2", name="Alice",
                               reports_to_id=admin_e.id, user_id=alice.id)

        proc.create_vendor(s, name="Acme Supplies", is_1099=True)
        sls.create_customer(s, name="Beta Corp")
        cash = acct.get_account_by_role(s, "cash")
        bank_svc.create_bank_account(s, name="Checking", gl_account_id=cash.id,
                                     account_no_masked="****1234")
        widget = inv.create_product(s, sku="WIDGET-1", name="Widget",
                                    type=ProductType.INVENTORY, standard_cost=5)
        s.flush()

        # some on-hand stock so "how much stock?" is interesting
        inb = inv.create_inbound(s, received_date=date.today(),
                                 lines=[{"product_id": widget.id, "qty": 100, "unit_cost": 5}])
        inv.post_inbound(s, inb.id)

        # a pending request from Alice -> lands in Admin's approval inbox
        req = appr.create_request(
            s, type=RequestType.PURCHASE, requester_id=alice.id,
            title="Office chairs", description="ergonomic chairs",
            lines=[{"description": "chair", "qty": 5, "unit_price": 120}],
        )
        appr.submit_request(s, req.id)

        s.commit()
        print("Seeded. Logins: admin@001.local/admin (ADMIN), alice@001.local/alice (employee)")


if __name__ == "__main__":
    main()
