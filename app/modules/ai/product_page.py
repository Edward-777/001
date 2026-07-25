"""Read a product page the user linked (e.g. for a purchase request): fetch the
page LOCALLY, strip it to text, and let the LLM extract {title, price}.

The extracted price is a PREFILL, never an authority — it still goes through the
draft-confirm gate and the approver sees the URL as the double-check. Retail
sites (Amazon especially) often bot-block: failure is a designed outcome and the
caller must fall back to asking the user for the price.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

from . import llm

_TIMEOUT = 8.0
_MAX_BYTES = 1_000_000
_MAX_TEXT = 6_000
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_PROMPT = (
    "Below is the visible text of a retail product page. Extract ONLY a JSON object "
    '(no prose, no code fence):\n{"title": str|null, "price": number|null}\n'
    "price = the CURRENT selling price of the main product (not a struck-through "
    "list price, not a per-month figure, no currency symbol, plain number). "
    "Use null when it is not clearly stated. Return ONLY the JSON.\n\n"
)


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.chunks.append(data.strip())


def _assert_public_host(url: str) -> None:
    """SSRF guard — the server fetches an arbitrary user-supplied URL, so refuse
    anything that resolves to loopback/private/link-local address space."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are supported")
    host = parsed.hostname or ""
    for info in socket.getaddrinfo(host, None):
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError("refusing to fetch a private/internal address")


def fetch_page_text(url: str) -> str:
    """GET the page (size-capped, timeout, redirects) and strip it to plain text."""
    import httpx

    _assert_public_host(url)
    with httpx.Client(follow_redirects=True, timeout=_TIMEOUT,
                      headers={"User-Agent": _UA}) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            raw = b""
            for chunk in resp.iter_bytes():
                raw += chunk
                if len(raw) >= _MAX_BYTES:
                    break
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", "ignore"))
    text = " ".join(parser.chunks)
    return " ".join(text.split())[:_MAX_TEXT]


def extract_product(text: str) -> dict:
    """LLM extraction: {'title': str|None, 'price': float|None}."""
    msg = llm.chat([{"role": "user", "content": _PROMPT + text}])
    content = msg.get("content", "")
    i, j = content.find("{"), content.rfind("}")
    if i < 0 or j <= i:
        return {"title": None, "price": None}
    try:
        obj = json.loads(content[i:j + 1])
    except json.JSONDecodeError:
        return {"title": None, "price": None}
    price = obj.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {"title": obj.get("title"), "price": price}


def fetch_product(url: str) -> dict:
    """Fetch + extract; every failure comes back as {'error': ...} data."""
    try:
        text = fetch_page_text(url)
    except Exception as exc:
        return {"error": f"couldn't fetch the page ({type(exc).__name__})"}
    if not text:
        return {"error": "the page had no readable text"}
    out = extract_product(text)
    if out.get("price") is None:
        return {"error": "no clearly stated price on the page"}
    return out
