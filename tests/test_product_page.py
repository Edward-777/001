"""Link-based purchase requests: local page fetch (SSRF-guarded), LLM price
extraction as a PREFILL that still passes the draft-confirm gate, and the URL
surfacing to the approver as the double-check."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, approval, auth, hr  # noqa: F401  register
from app.modules.ai import product_page
from app.modules.ai.registry import registry
from app.modules.approval import service as appr
from app.modules.auth import service as auth_svc


# ---- fetch helper --------------------------------------------------------

def test_html_is_stripped_to_text():
    parser = product_page._TextExtractor()
    parser.feed("<html><head><title>x</title><script>evil()</script></head>"
                "<body><h1>ASUS Monitor</h1><style>.a{}</style><p>$199.99</p></body></html>")
    text = " ".join(parser.chunks)
    assert "ASUS Monitor" in text and "$199.99" in text
    assert "evil" not in text and ".a{}" not in text


def test_private_addresses_are_refused(monkeypatch):
    monkeypatch.setattr(product_page.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(ValueError, match="private"):
        product_page._assert_public_host("http://internal.example/admin")
    with pytest.raises(ValueError, match="http"):
        product_page._assert_public_host("file:///etc/passwd")


def test_extract_product_parses_llm_json(monkeypatch):
    monkeypatch.setattr(product_page.llm, "chat",
                        lambda msgs, **kw: {"content": '{"title": "ASUS 27in", "price": 199.99}'})
    out = product_page.extract_product("some page text")
    assert out == {"title": "ASUS 27in", "price": 199.99}
    monkeypatch.setattr(product_page.llm, "chat", lambda msgs, **kw: {"content": "no json here"})
    assert product_page.extract_product("x")["price"] is None


# ---- tool integration ----------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def employee(session):
    return auth_svc.create_user(session, name="Emp", email="e@x", password="pw")


def test_url_price_prefills_draft_with_verify_flag(session, employee, monkeypatch):
    monkeypatch.setattr(product_page, "fetch_product",
                        lambda url: {"title": "ASUS 27in Monitor", "price": 199.99})
    out = registry.execute("create_purchase_request",
                           {"title": "Monitor", "qty": 2,
                            "product_url": "https://shop.example/asus-27"},
                           session=session, user=employee)["result"]
    assert out["needs_confirmation"] is True
    assert out["total_amount"] == "399.98"
    assert "verify" in out["confirm"]
    line = appr.request_lines(session, 1)[0]
    assert line.product_url == "https://shop.example/asus-27"
    assert line.price_source == "url"
    assert "ASUS 27in Monitor" in line.description


def test_fetch_failure_asks_user_and_creates_nothing(session, employee, monkeypatch):
    monkeypatch.setattr(product_page, "fetch_product",
                        lambda url: {"error": "couldn't fetch the page (HTTPStatusError)"})
    out = registry.execute("create_purchase_request",
                           {"title": "Monitor", "qty": 2,
                            "product_url": "https://amazon.example/x"},
                           session=session, user=employee)["result"]
    assert "ask the user" in out["error"]
    assert appr.list_requests_for_user(session, employee.id) == []


def test_user_price_beats_url(session, employee, monkeypatch):
    def boom(url):  # the fetcher must not even be called
        raise AssertionError("fetch_product called despite a user price")
    monkeypatch.setattr(product_page, "fetch_product", boom)
    out = registry.execute("create_purchase_request",
                           {"title": "Monitor", "qty": 1, "unit_price": 180,
                            "product_url": "https://shop.example/asus-27"},
                           session=session, user=employee)["result"]
    assert out["total_amount"] == "180.00"
    line = appr.request_lines(session, 1)[0]
    assert line.price_source == "user"
    assert line.product_url == "https://shop.example/asus-27"  # link still attached
