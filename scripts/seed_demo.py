"""Seed a RICH demo company so you can actually test (reports, aging, AI all have
real content). Everything posts through the real services, so the books balance.

Usage:  python -m scripts.seed_demo          (refuses if already seeded)
        python -m scripts.seed_demo --fresh  (drops dev.db first)

Logins (all password = the name):
  admin@001.local / admin   ADMIN      (CEO — full access incl. financials)
  cfo@001.local   / cfo      ACCOUNTANT (finance)
  mgr@001.local   / mgr      MANAGER    (ops + approvals)
  alice@001.local / alice    EMPLOYEE
  bob@001.local   / bob      EMPLOYEE
"""
from __future__ import annotations

import sys
from datetime import date

from app.core.db import Base, SessionLocal, engine
from app.modules import (  # noqa: F401  register all tables
    accounting, ai, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.approval import service as appr
from app.modules.approval.models import RequestType
from app.modules.assets import service as asset_svc
from app.modules.expense import service as expense_svc
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role
from app.modules.bank import service as bank_svc
from app.modules.hr import service as hr_svc
from app.modules.inventory import service as inv
from app.modules.inventory.models import OutboundType, ProductType
from app.modules.procurement import service as proc
from app.modules.sales import service as sls
from app.wiring import register_all_handlers


def main(fresh: bool = False) -> None:
    if fresh:
        import os
        from pathlib import Path

        for p in (Path("dev.db"),):
            if p.exists():
                os.remove(p)

    Base.metadata.create_all(engine)
    register_all_handlers()  # so inbound/outbound/AR events actually post to the GL

    with SessionLocal() as s:
        if auth_svc.authenticate(s, "admin@001.local", "admin"):
            print("Already seeded. Use --fresh to rebuild.")
            return

        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        appr.seed_approval_rules(s)

        # ---- people + org chart -----------------------------------------
        admin = auth_svc.create_user(s, name="Edward (CEO)", email="admin@001.local", password="admin", role=Role.ADMIN)
        cfo = auth_svc.create_user(s, name="Fiona (CFO)", email="cfo@001.local", password="cfo", role=Role.ACCOUNTANT)
        mgr = auth_svc.create_user(s, name="Marco (Ops Mgr)", email="mgr@001.local", password="mgr", role=Role.MANAGER)
        alice = auth_svc.create_user(s, name="Alice", email="alice@001.local", password="alice", role=Role.EMPLOYEE)
        bob = auth_svc.create_user(s, name="Bob", email="bob@001.local", password="bob", role=Role.EMPLOYEE)
        s.flush()
        ops = hr_svc.create_department(s, name="Operations")
        fin = hr_svc.create_department(s, name="Finance")
        e_admin = hr_svc.create_employee(s, employee_no="E1", name="Edward", user_id=admin.id)
        hr_svc.create_employee(s, employee_no="E2", name="Fiona", department_id=fin.id, reports_to_id=e_admin.id, user_id=cfo.id)
        e_mgr = hr_svc.create_employee(s, employee_no="E3", name="Marco", department_id=ops.id, reports_to_id=e_admin.id, user_id=mgr.id)
        e_alice = hr_svc.create_employee(s, employee_no="E4", name="Alice", department_id=ops.id, reports_to_id=e_mgr.id, user_id=alice.id)
        hr_svc.create_employee(s, employee_no="E5", name="Bob", department_id=ops.id, reports_to_id=e_mgr.id, user_id=bob.id)

        # ---- masters ----------------------------------------------------
        acme = proc.create_vendor(s, name="Acme Supplies", is_1099=True)
        dell = proc.create_vendor(s, name="Dell Inc.")
        depot = proc.create_vendor(s, name="Office Depot")
        beta = sls.create_customer(s, name="Beta Corp")
        gamma = sls.create_customer(s, name="Gamma LLC")
        delta = sls.create_customer(s, name="Delta Inc.")

        widget_a = inv.create_product(s, sku="WIDGET-A", name="Widget A", standard_cost=10)
        widget_b = inv.create_product(s, sku="WIDGET-B", name="Widget B", standard_cost=18)
        cable = inv.create_product(s, sku="CABLE-1", name="HDMI Cable", standard_cost=4)
        laptop = inv.create_product(s, sku="LAPTOP-DELL", name="Dell Laptop", type=ProductType.ASSET,
                                    model_name="Latitude 5540", track_serial=True, standard_cost=1200)
        s.flush()

        cash = acct.get_account_by_role(s, "cash")
        bank_svc.create_bank_account(s, name="Checking", gl_account_id=cash.id, account_no_masked="****1234")

        # ---- procurement: receive stock -> vendor bill -> 3-way match ---
        def procure(vendor, product, qty, cost, when, pay=False):
            inb = inv.create_inbound(s, received_date=when, lines=[{"product_id": product.id, "qty": qty, "unit_cost": cost}])
            inv.post_inbound(s, inb.id)
            bill = acct.create_ap_bill(
                s, vendor_id=vendor.id, bill_date=when, due_date=date(when.year, when.month, 28),
                vendor_invoice_no=f"INV-{vendor.id}{qty}{when.month}",
                lines=[{"description": product.name, "qty": qty, "unit_price": cost,
                        "inbound_line_id": inb.lines[0].id}],
            )
            acct.match_ap_bill(s, bill.id)
            if pay:
                acct.create_payment(s, vendor_id=vendor.id, payment_date=when,
                                    applications=[{"ap_bill_id": bill.id, "amount": float(bill.amount)}])
            return bill

        procure(acme, widget_a, 200, 10, date(2026, 2, 5), pay=True)
        procure(acme, widget_b, 100, 18, date(2026, 2, 12), pay=True)
        procure(depot, cable, 300, 4, date(2026, 3, 3), pay=False)   # leaves an open payable
        procure(acme, widget_a, 150, 11, date(2026, 4, 8), pay=False)  # open payable + moving avg
        procure(dell, laptop, 5, 1200, date(2026, 3, 15), pay=True)  # asset-type -> fixed assets

        # ---- sales: ship (COGS) -> invoice (revenue+tax) -> receipt -----
        def sell(customer, product, qty, price, when, collect=None):
            ob = inv.create_outbound(s, type=OutboundType.SALE, issue_date=when,
                                     lines=[{"product_id": product.id, "qty": qty}])
            inv.post_outbound(s, ob.id)
            invoice = sls.post_ar_invoice(s, customer_id=customer.id, invoice_date=when,
                                          due_date=date(when.year, when.month, 28), tax_rate=8,
                                          lines=[{"product_id": product.id, "description": product.name,
                                                  "qty": qty, "unit_price": price}])
            if collect:
                sls.post_receipt(s, customer_id=customer.id, receipt_date=when,
                                 applications=[{"ar_invoice_id": invoice.id, "amount": collect}])
            return invoice

        sell(beta, widget_a, 40, 25, date(2026, 2, 20), collect=1080)   # fully paid (40*25*1.08)
        sell(gamma, widget_b, 30, 40, date(2026, 3, 10), collect=600)   # partial -> open AR
        sell(delta, widget_a, 25, 26, date(2026, 4, 18))                # unpaid -> AR aging

        # ---- depreciation on the fixed assets (best-effort) -------------
        try:
            for period in ("2026-03", "2026-04", "2026-05"):
                asset_svc.run_depreciation(s, period=period)
        except Exception as exc:  # noqa: BLE001
            print(f"(skipped depreciation: {exc})")

        # ---- expense claim (best-effort) --------------------------------
        try:
            claim = expense_svc.create_expense_claim(
                s, requester_user_id=alice.id, employee_id=e_alice.id,
                title="SF conference trip", description="2-day conference",
                lines=[{"description": "airfare", "amount": 450, "expense_date": date(2026, 4, 2)},
                       {"description": "hotel", "amount": 620, "expense_date": date(2026, 4, 3)}],
            )
            if getattr(claim, "request_id", None):
                appr.submit_request(s, claim.request_id)  # lands in Marco's approval inbox
        except Exception as exc:  # noqa: BLE001
            print(f"(skipped expense claim: {exc})")

        # ---- a couple of pending approvals for the inbox ----------------
        for title, qty, price in [("New monitors x5", 5, 220), ("Standing desks x2", 2, 480)]:
            req = appr.create_request(s, type=RequestType.PURCHASE, requester_id=bob.id, title=title,
                                      lines=[{"description": title, "qty": qty, "unit_price": price}])
            appr.submit_request(s, req.id)

        # ---- close the books for February -------------------------------
        try:
            acct.close_period(s, "2026-02", closed_by=cfo.id)
        except Exception as exc:  # noqa: BLE001
            print(f"(skipped period close: {exc})")

        # ---- ingest the travel policy into RAG, if present (best-effort) -
        try:
            import os

            from app.modules.ai import invoice as doc
            from app.modules.ai import rag
            policy = os.path.expanduser("~/Downloads/05. Travel and Expense Policy v11.docx")
            if os.path.exists(policy):
                n = rag.ingest(s, source="Travel & Expense Policy",
                               text=doc.extract_text(policy), acl_scope="general")
                print(f"Ingested Travel & Expense Policy ({n} chunks).")
        except Exception as exc:  # noqa: BLE001
            print(f"(skipped policy ingest — Ollama not running? {exc})")

        s.commit()
        bs = acct.balance_sheet(s, as_of=date(2026, 5, 31))
        print("Seeded demo company. Logins: admin/cfo/mgr/alice/bob @001.local (pwd = name).")
        print(f"Balance sheet 2026-05-31: assets {bs['total_assets']} = "
              f"liab {bs['total_liabilities']} + equity {bs['total_equity']}  balanced={bs['balanced']}")


if __name__ == "__main__":
    main(fresh="--fresh" in sys.argv)
