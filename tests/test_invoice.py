"""Invoice parsing (Phase 3 endgame). The vision call is mocked for determinism;
the live accuracy is verified manually on the 4090."""
import pytest

from app.modules.ai import invoice
from app.modules.ai import llm

_SAMPLE = """Here is the data:
```json
{"vendor_name": "INSIGHT DIRECT USA INC", "invoice_no": "0335662565",
 "invoice_date": "2024-03-27", "currency": "USD", "po_number": "DELL R650",
 "lines": [{"description": "DELL POWEREDGE R650", "qty": 1, "unit_price": 16285.53, "amount": 16285.53}],
 "subtotal": 16285.53, "freight": 24.21, "tax": 1345.55, "total": 17655.29}
```"""


def test_extract_json_handles_fence_and_prose():
    d = invoice._extract_json(_SAMPLE)
    assert d["vendor_name"] == "INSIGHT DIRECT USA INC"
    assert d["total"] == 17655.29


def test_extract_json_rejects_non_json():
    with pytest.raises(ValueError):
        invoice._extract_json("no json here")


def test_parse_invoice_returns_structured_fields(monkeypatch):
    monkeypatch.setattr(invoice, "load_images", lambda path: [b"fakepng"])
    monkeypatch.setattr(llm, "vision_chat", lambda prompt, images: _SAMPLE)
    d = invoice.parse_invoice("anything.pdf")
    assert d["invoice_no"] == "0335662565"
    assert d["invoice_date"] == "2024-03-27"
    assert d["lines"][0]["unit_price"] == 16285.53
    assert d["total"] == 17655.29


def test_unsupported_file_type_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        invoice._load_images("notes.txt")
