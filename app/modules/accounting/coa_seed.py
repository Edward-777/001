"""Default Chart of Accounts — US small business, QuickBooks-style (SCHEMA §Q5).

Each tuple: (code, name, type, subtype, system_role).
`system_role` anchors the M4 posting engine; every role referenced in
ARCHITECTURE §4's posting table is present here.
"""
from .models import AccountType as T

# fmt: off
DEFAULT_COA: list[tuple[str, str, str, str | None, str | None]] = [
    # --- Assets ---
    ("1000", "Checking",                 T.ASSET, "bank",                "cash"),
    ("1010", "Savings",                  T.ASSET, "bank",                None),
    ("1100", "Undeposited Funds",        T.ASSET, "current_asset",       None),
    ("1200", "Accounts Receivable",      T.ASSET, "accounts_receivable", "ar"),
    ("1300", "Inventory Asset",          T.ASSET, "current_asset",       "inventory"),
    ("1500", "Equipment",                T.ASSET, "fixed_asset",         "fixed_asset"),
    ("1510", "Accumulated Depreciation", T.ASSET, "fixed_asset",         "accum_deprec"),
    # --- Liabilities ---
    ("2000", "Accounts Payable",         T.LIABILITY, "accounts_payable",   "ap"),
    ("2050", "GR/IR Clearing",           T.LIABILITY, "current_liability",  "gr_ir"),
    ("2100", "Sales Tax Payable",        T.LIABILITY, "current_liability",  "sales_tax"),
    ("2200", "Employee Reimbursements",  T.LIABILITY, "current_liability",  "employee_payable"),
    # --- Equity ---
    ("3000", "Opening Balance Equity",   T.EQUITY, "equity", "opening_balance_equity"),
    ("3100", "Owner's Equity",           T.EQUITY, "equity", None),
    ("3900", "Retained Earnings",        T.EQUITY, "equity", "retained_earnings"),
    # --- Revenue ---
    ("4000", "Sales Income",             T.REVENUE, "income", "revenue"),
    ("4100", "Service Income",           T.REVENUE, "income", None),
    # --- Expense ---
    ("5000", "Cost of Goods Sold",       T.EXPENSE, "cogs",    "cogs"),
    ("5900", "Inventory Shrinkage",      T.EXPENSE, "expense", "inventory_loss"),
    ("6000", "Payroll Expenses",         T.EXPENSE, "expense", None),
    ("6100", "Rent Expense",             T.EXPENSE, "expense", None),
    ("6200", "Travel Expense",           T.EXPENSE, "expense", "travel_expense"),
    ("6300", "Office Supplies",          T.EXPENSE, "expense", "supplies_expense"),
    ("6400", "Bank Service Charges",     T.EXPENSE, "expense", "bank_fees"),
    ("6900", "Depreciation Expense",     T.EXPENSE, "expense", "deprec_expense"),
]
# fmt: on
