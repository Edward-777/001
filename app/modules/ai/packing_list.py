"""Supplier packing list / delivery note parsing (local vision model).

Packing lists carry WHAT arrived and HOW MANY — usually no prices. The parsed
lines are matched to an open PO and drafted as an (unposted) goods receipt for
the founder to approve in /fleet; valuation comes from the PO, never the model.
"""
from __future__ import annotations

from . import invoice, llm

_PROMPT = (
    "Extract this supplier packing list / delivery note as ONLY a JSON object "
    "(no prose, no code fence):\n"
    '{"vendor_name": str, "po_number": str|null, "delivery_date": "YYYY-MM-DD"|null, '
    '"lines": [{"description": str, "sku": str|null, "qty": number}]}\n'
    "po_number = the buyer's purchase-order number referenced on the document "
    "(often labeled PO / Customer PO / Order no). qty must be a plain number. "
    "Return ONLY the JSON."
)


def parse_packing_list(path: str) -> dict:
    """Vision-parse a packing list file into the dict above."""
    return invoice._extract_json(llm.vision_chat(_PROMPT, invoice.load_images(path)))
