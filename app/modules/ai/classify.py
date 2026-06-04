"""Document classification (DESIGN §8.4 — the linchpin). On upload, a local
vision model decides what a document IS, which drives BOTH security (its ACL
scope/level — DESIGN §8.5) and automation (which workflow it routes to).

Default-Deny: an unrecognized document is treated as 'other' — readable at the
general level but NOT indexed into RAG, so junk can't pollute retrieval (§8.6).
"""
from __future__ import annotations

from . import llm

CATEGORIES = ("invoice", "bank_statement", "receipt", "policy", "contract", "other")

# category -> (acl_scope, acl_level, route, index_into_rag)
_ROUTING: dict[str, tuple[str, int, str, bool]] = {
    "invoice":        ("finance", 2, "ap_bill", False),
    "bank_statement": ("finance", 2, "reconcile", False),
    "receipt":        ("finance", 1, "expense", False),
    "policy":         ("general", 1, "rag", True),
    "contract":       ("finance", 3, "store", False),
    "other":          ("general", 1, "store", False),
}

_PROMPT = (
    "Classify this business document into EXACTLY ONE category from this list: "
    "invoice, bank_statement, receipt, policy, contract, other. "
    "Reply with ONLY the single category word, nothing else."
)


def _pick(raw: str) -> str:
    raw = (raw or "").strip().lower()
    for cat in CATEGORIES:
        if cat in raw:
            return cat
    return "other"


def classify(images: list[bytes]) -> str:
    """Classify a rendered (image) document with the vision model."""
    return _pick(llm.vision_chat(_PROMPT, images))


def classify_text(text: str) -> str:
    """Classify a text document (csv/docx/txt) with the text model."""
    raw = llm.chat([
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": (text or "")[:4000]},
    ]).get("content", "")
    return _pick(raw)


def classify_file(path: str) -> str:
    """Classify any uploaded file — render images for PDFs/images, else use text.
    CSVs get a content heuristic first (a date+amount export is a transaction list)."""
    from pathlib import Path

    from . import invoice

    ext = Path(path).suffix.lower()
    if ext in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        return classify(invoice.load_images(path))
    if ext == ".csv":
        head = Path(path).read_text(encoding="utf-8", errors="ignore")[:500].lower()
        if "amount" in head and any(k in head for k in ("date", "description", "balance")):
            return "bank_statement"
    return classify_text(invoice.extract_text(path))


def routing_for(category: str) -> tuple[str, int, str, bool]:
    """(acl_scope, acl_level, route, index_into_rag) for a category."""
    return _ROUTING.get(category, _ROUTING["other"])
