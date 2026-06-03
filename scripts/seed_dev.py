"""Seed a runnable dev database: COA, rules, an admin + a small org.

Usage:  python -m scripts.seed_dev
Login:  admin@001.local / admin   (approver: ceo@001.local / ceo)
"""
from app.core.db import Base, SessionLocal, engine
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.approval import service as appr
from app.modules.auth import service as auth_svc
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

        ceo_u = auth_svc.create_user(s, name="CEO", email="ceo@001.local", password="ceo", role=Role.ADMIN)
        admin_u = auth_svc.create_user(s, name="Admin", email="admin@001.local", password="admin", role=Role.MANAGER)
        s.flush()
        ceo_e = hr_svc.create_employee(s, employee_no="E1", name="CEO", user_id=ceo_u.id)
        hr_svc.create_employee(s, employee_no="E2", name="Admin", reports_to_id=ceo_e.id, user_id=admin_u.id)

        proc.create_vendor(s, name="Acme Supplies", is_1099=True)
        sls.create_customer(s, name="Beta Corp")
        inv.create_product(s, sku="WIDGET-1", name="Widget", type=ProductType.INVENTORY, standard_cost=5)
        s.commit()
        print("Seeded. Login: admin@001.local / admin  (approver: ceo@001.local / ceo)")


if __name__ == "__main__":
    main()
