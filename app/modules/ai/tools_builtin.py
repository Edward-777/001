"""Built-in AI tools — thin wrappers over module services (AI-AGENT §2).

Each handler runs as the calling user; results are JSON-serializable dicts the
model reads back. `get_financials` carries scope=(finance,3) — an employee asking
the AI for the GL is denied exactly like the UI route (permission inheritance)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..accounting import service as acct
from ..approval import service as appr
from ..approval.service import RequestType
from ..auth.models import User
from ..inventory import service as inv
from ..procurement import service as proc
from ..sales import service as sls
from . import rag
from .registry import Registry, Tool


def _create_purchase_request(session: Session, user: User, args: dict) -> dict:
    # Require concrete amounts — never create a record with guessed/empty values.
    qty = float(args.get("qty") or 0)
    price = float(args.get("unit_price") or 0)
    if qty <= 0 or price <= 0:
        return {"error": "need quantity AND unit_price (both > 0) before creating — "
                         "ask the user for the missing values first"}
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=user.id,
        title=args["title"], description=args.get("description", ""),
        lines=[{"description": args.get("description") or args["title"],
                "qty": qty, "unit_price": price}],
    )
    appr.submit_request(session, req.id)
    return {"request_no": req.request_no, "status": req.status,
            "total_amount": str(req.total_amount)}


def _create_expense_request(session: Session, user: User, args: dict) -> dict:
    """Travel/expense reimbursement request — so a trip is NOT a purchase order."""
    amount = float(args.get("amount") or 0)
    if amount <= 0:
        return {"error": "need a total amount (> 0) — ask the user for the figure first"}
    kind = RequestType.TRIP if args.get("kind") == "trip" else RequestType.EXPENSE
    req = appr.create_request(
        session, type=kind, requester_id=user.id, title=args["title"],
        description=args.get("description", ""),
        lines=[{"description": args.get("description") or args["title"], "qty": 1,
                "unit_price": amount}],
    )
    appr.submit_request(session, req.id)
    return {"request_no": req.request_no, "type": req.type, "status": req.status,
            "total_amount": str(req.total_amount)}


def _list_my_requests(session: Session, user: User, args: dict) -> list[dict]:
    return [{"request_no": r.request_no, "type": r.type, "title": r.title,
             "amount": str(r.total_amount), "status": r.status}
            for r in appr.list_requests_for_user(session, user.id, limit=20)]


def _list_products(session: Session, user: User, args: dict) -> list[dict]:
    out = []
    for p in inv.list_products(session):
        bal = inv.get_stock(session, p.id)
        out.append({"sku": p.sku, "name": p.name, "type": p.type,
                    "qty_on_hand": str(bal.qty_on_hand) if bal else "0"})
    return out


def _list_vendors(session: Session, user: User, args: dict) -> list[dict]:
    return [{"name": v.name, "terms": v.payment_terms} for v in proc.list_vendors(session)]


def _list_customers(session: Session, user: User, args: dict) -> list[dict]:
    return [{"name": c.name, "terms": c.payment_terms} for c in sls.list_customers(session)]


def _get_ap_aging(session: Session, user: User, args: dict) -> dict:
    a = acct.ap_aging(session, as_of=date.today())
    return {"total": str(a["total"]), "buckets": {k: str(v) for k, v in a["buckets"].items()}}


def _get_ar_aging(session: Session, user: User, args: dict) -> dict:
    a = acct.ar_aging(session, as_of=date.today())
    return {"total": str(a["total"]), "buckets": {k: str(v) for k, v in a["buckets"].items()}}


def _get_inventory_valuation(session: Session, user: User, args: dict) -> dict:
    v = acct.inventory_valuation(session)
    return {"total_value": str(v["total_value"]),
            "items": [{"product_id": r["product_id"], "qty": str(r["qty"]),
                       "value": str(r["value"])} for r in v["rows"]]}


def _get_trial_balance(session: Session, user: User, args: dict) -> dict:
    tb = acct.trial_balance(session, as_of=date.today())
    return {"balanced": tb["balanced"], "total_debit": str(tb["total_debit"]),
            "total_credit": str(tb["total_credit"]),
            "rows": [{"code": r["code"], "name": r["name"],
                      "debit": str(r["debit"]), "credit": str(r["credit"])} for r in tb["rows"]]}


def _list_my_approvals(session: Session, user: User, args: dict) -> list[dict]:
    return [{"id": r.id, "request_no": r.request_no, "title": r.title,
             "amount": str(r.total_amount)} for r in appr.pending_for_user(session, user.id)]


def _approve_request(session: Session, user: User, args: dict) -> dict:
    req = appr.approve(session, int(args["request_id"]), user.id)
    return {"request_no": req.request_no, "status": req.status}


def _get_stock(session: Session, user: User, args: dict) -> dict:
    p = inv.get_product_by_sku(session, args["sku"])
    if p is None:
        return {"error": "product not found"}
    bal = inv.get_stock(session, p.id)
    return {"sku": p.sku, "name": p.name,
            "qty_on_hand": str(bal.qty_on_hand) if bal else "0",
            "avg_unit_cost": str(bal.avg_unit_cost) if bal else "0"}


def _search_company_policy(session: Session, user: User, args: dict) -> dict:
    hits = rag.search(session, args["query"], user=user, top_k=4)
    if not hits:
        return {"passages": [], "note": "no matching company document found"}
    return {"passages": [{"source": h["source"], "text": h["content"]} for h in hits]}


def _get_financials(session: Session, user: User, args: dict) -> dict:
    fin = acct.generate_financials(session, args["period"])
    is_, bs = fin["income_statement"], fin["balance_sheet"]
    return {"period": fin["period"], "net_income": str(is_["net_income"]),
            "total_assets": str(bs["total_assets"]), "balanced": bs["balanced"]}


_BUILTIN = [
    Tool(
        name="create_purchase_request",
        description="Create and submit a purchase request for approval (routes via the org chart).",
        parameters={"type": "object", "properties": {
            "title": {"type": "string"}, "description": {"type": "string"},
            "qty": {"type": "number"}, "unit_price": {"type": "number"}}, "required": ["title"]},
        handler=_create_purchase_request,
    ),
    Tool(
        name="list_my_approvals",
        description="List requests currently awaiting the current user's approval.",
        parameters={"type": "object", "properties": {}},
        handler=_list_my_approvals,
    ),
    Tool(
        name="approve_request",
        description="Approve a request that is awaiting the current user's approval.",
        parameters={"type": "object", "properties": {"request_id": {"type": "integer"}},
                    "required": ["request_id"]},
        handler=_approve_request,
    ),
    Tool(
        name="get_stock",
        description="Get on-hand quantity and average cost for a product by SKU.",
        parameters={"type": "object", "properties": {"sku": {"type": "string"}},
                    "required": ["sku"]},
        handler=_get_stock, scope="inventory", level=1,
    ),
    Tool(
        name="get_financials",
        description="Get the financial close for a period (YYYY-MM): net income, total assets.",
        parameters={"type": "object", "properties": {"period": {"type": "string"}},
                    "required": ["period"]},
        handler=_get_financials, scope="finance", level=3,  # GL access — inherits caller's scope
    ),
    Tool(
        name="search_company_policy",
        description=("Search the company's internal policies and documents (e.g. the Travel & "
                     "Expense Policy) for relevant passages. ALWAYS use this to answer questions "
                     "about company rules, policy, limits, or what is allowed — never answer "
                     "policy questions from your own assumptions."),
        parameters={"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"]},
        handler=_search_company_policy,  # company policy is readable by all staff (chunk ACL applies)
    ),
    Tool(
        name="create_expense_request",
        description=("Submit a travel or expense reimbursement request for approval. Use this "
                     "for trips, meals, and out-of-pocket costs — NOT for buying goods (that is "
                     "create_purchase_request). Requires a concrete total amount."),
        parameters={"type": "object", "properties": {
            "title": {"type": "string"}, "amount": {"type": "number"},
            "description": {"type": "string"},
            "kind": {"type": "string", "enum": ["expense", "trip"]}}, "required": ["title", "amount"]},
        handler=_create_expense_request,
    ),
    Tool(
        name="list_my_requests",
        description="List the current user's own requests (purchase/expense/trip) with status.",
        parameters={"type": "object", "properties": {}},
        handler=_list_my_requests,
    ),
    Tool(
        name="list_products",
        description="List products with SKU, name, type, and on-hand quantity.",
        parameters={"type": "object", "properties": {}},
        handler=_list_products, scope="inventory", level=1,
    ),
    Tool(
        name="list_vendors",
        description="List active vendors (suppliers).",
        parameters={"type": "object", "properties": {}},
        handler=_list_vendors, scope="procurement", level=1,
    ),
    Tool(
        name="list_customers",
        description="List active customers.",
        parameters={"type": "object", "properties": {}},
        handler=_list_customers, scope="finance", level=1,
    ),
    Tool(
        name="get_ap_aging",
        description="Accounts Payable aging (what we owe vendors) by due bucket.",
        parameters={"type": "object", "properties": {}},
        handler=_get_ap_aging, scope="finance", level=3,
    ),
    Tool(
        name="get_ar_aging",
        description="Accounts Receivable aging (what customers owe us) by due bucket.",
        parameters={"type": "object", "properties": {}},
        handler=_get_ar_aging, scope="finance", level=3,
    ),
    Tool(
        name="get_inventory_valuation",
        description="Total inventory value on hand (moving average) and per-product breakdown.",
        parameters={"type": "object", "properties": {}},
        handler=_get_inventory_valuation, scope="inventory", level=2,
    ),
    Tool(
        name="get_trial_balance",
        description="Trial balance (all account balances, debits and credits) as of today.",
        parameters={"type": "object", "properties": {}},
        handler=_get_trial_balance, scope="finance", level=3,
    ),
]


def register_builtin_tools(reg: Registry) -> None:
    for t in _BUILTIN:
        reg.register(t)
