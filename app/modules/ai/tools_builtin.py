"""Built-in AI tools — thin wrappers over module services (AI-AGENT §2).

Each handler runs as the calling user; results are JSON-serializable dicts the
model reads back. `get_financials` carries scope=(finance,3) — an employee asking
the AI for the GL is denied exactly like the UI route (permission inheritance)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..accounting import service as acct
from ..approval import service as appr
from ..approval.service import RequestType
from ..auth.models import User
from ..inventory import service as inv
from . import rag
from .registry import Registry, Tool


def _create_purchase_request(session: Session, user: User, args: dict) -> dict:
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=user.id,
        title=args["title"], description=args.get("description", ""),
        lines=[{"description": args.get("description") or args["title"],
                "qty": args.get("qty", 1), "unit_price": args.get("unit_price", 0)}],
    )
    appr.submit_request(session, req.id)
    return {"request_no": req.request_no, "status": req.status,
            "total_amount": str(req.total_amount)}


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
]


def register_builtin_tools(reg: Registry) -> None:
    for t in _BUILTIN:
        reg.register(t)
