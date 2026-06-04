"""Invoice parsing (Phase 3 endgame): render a PDF/image invoice and read it with
a local vision model (qwen2.5-vl) into structured fields. Fully local — the
document never leaves the box.

The parsed result is a SUGGESTION: the user/agent confirms before it becomes an
AP bill, and amounts that drive accounting are reconciled against the receipt
(3-way match), so a parsing slip can't silently post a wrong number.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import llm

_PROMPT = (
    "You are an invoice data extractor. Read the invoice image(s) and return ONLY a "
    "JSON object (no prose, no code fence) with exactly these keys:\n"
    '{"vendor_name": str, "invoice_no": str, "invoice_date": "YYYY-MM-DD", '
    '"currency": str, "po_number": str|null, '
    '"lines": [{"description": str, "qty": number, "unit_price": number, "amount": number}], '
    '"subtotal": number, "freight": number, "tax": number, "total": number}\n'
    "Rules: copy values exactly as printed; numbers must be plain (no commas, no "
    "currency symbols); convert dates like 27-MAR-2024 to 2024-03-27; use null for "
    "any field that is absent. Return ONLY the JSON object."
)


def _pdf_to_images(path: str, *, max_pages: int = 2, dpi: int = 170) -> list[bytes]:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    images: list[bytes] = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        images.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    doc.close()
    return images


def load_images(path: str) -> list[bytes]:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _pdf_to_images(path)
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return [Path(path).read_bytes()]
    raise ValueError(f"unsupported invoice file type: {ext}")


_load_images = load_images  # back-compat alias


def extract_text(path: str) -> str:
    """Plain text of a document (for RAG ingest of policies/contracts)."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        import fitz

        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    if ext in (".txt", ".md"):
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    if ext == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(path).paragraphs if p.text.strip())
    return ""


def _extract_json(raw: str) -> dict:
    i, j = raw.find("{"), raw.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("vision model returned no JSON")
    return json.loads(raw[i:j + 1])


def parse_from_images(images: list[bytes]) -> dict:
    return _extract_json(llm.vision_chat(_PROMPT, images))


def parse_invoice(path: str) -> dict:
    """Render the invoice and extract structured fields with the vision model."""
    return parse_from_images(load_images(path))
