"""Default posting rules (ARCHITECTURE §4) — simple 2-line events.

Each tuple: (event_type, condition, debit_role, credit_role).
Multi-line events (asset->inventory reclass, AR invoice + sales tax, expense by
category) are posted with explicit lines in their own module handlers (M8/M9/M11),
still resolving roles via accounting.get_account_by_role.
"""
DEFAULT_POSTING_RULES: list[tuple[str, str | None, str, str]] = [
    ("inbound.posted",     "inventory", "inventory",        "gr_ir"),
    ("inbound.posted",     "asset",     "fixed_asset",      "gr_ir"),
    ("ap_bill.matched",    None,        "gr_ir",            "ap"),
    ("payment.posted",     None,        "ap",               "cash"),
    ("outbound.posted",    "sale",        "cogs",             "inventory"),
    ("outbound.posted",    "disposal",    "inventory_loss",   "inventory"),
    ("outbound.posted",    "consumption", "supplies_expense", "inventory"),
    ("reclass.posted",     "inv_to_asset", "fixed_asset",   "inventory"),
    ("depreciation.run",   None,        "deprec_expense",   "accum_deprec"),
    ("receipt.posted",     None,        "cash",             "ar"),
    ("reimburse.posted",   None,        "employee_payable", "cash"),
    ("bank.fee",           None,        "bank_fees",        "cash"),
]
