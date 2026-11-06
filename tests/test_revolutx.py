import base64, json
from decimal import Decimal
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from bot.revolutx.client import RevolutXClient, RevolutXError, build_message, sign_message, load_private_key
from bot.revolutx.rules import PairRules, pairs_to_rules
from bot.brokers.revolutx import RevolutXBroker
from bot.brokers import make_broker, PaperBroker
from bot.config import Config

DOC_MSG = ('1765360896219POST/api/1.0/orders{"client_order_id":"3b364427-1f4f-4f66-9935-86b6fb115d26",'
           '"symbol":"BTC-USD","side":"BUY","order_configuration":{"limit":{"base_size":"0.1","price":"90000.1"}}}')


class Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self._d, self.headers = status, data, headers or {}
        self.content = b"" if data is None else json.dumps(data).encode()
        self.text = self.content.decode()
    def json(self): return self._d


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []
    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        for (m, frag), resp in self.routes.items():
            if m == method and frag in url:
                return resp.pop(0) if isinstance(resp, list) else resp
        raise AssertionError(f"rota inesperada {method} {url}")


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


def pem(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def test_message_matches_docs_example():
    body = {"client_order_id": "3b364427-1f4f-4f66-9935-86b6fb115d26", "symbol": "BTC-USD", "side": "BUY",
            "order_configuration": {"limit": {"base_size": "0.1", "price": "90000.1"}}}
    from bot.revolutx.client import minify
    assert build_message(1765360896219, "post", "/api/1.0/orders", "", minify(body)).decode() == DOC_MSG


def test_signature_verifies_and_is_deterministic(key):
    k = load_private_key(pem(key))
    s1, s2 = sign_message(k, DOC_MSG.encode()), sign_message(k, DOC_MSG.encode())
    assert s1 == s2 and len(base64.b64decode(s1)) == 64
    key.public_key().verify(base64.b64decode(s1), DOC_MSG.encode())  # lança se inválida


def test_rejects_non_ed25519():
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(ValueError):
        load_private_key(pem(k))


def test_signed_request_headers_and_query(key):
    s = FakeSession({("GET", "/orders/active"): Resp(200, {"data": [{"id": 1}], "metadata": {}})})
    c = RevolutXClient("K" * 64, key, session=s, clock=lambda: 1765360896.219, sleep=lambda x: None)
    c.active_orders(symbols=["BTC-USD", "ETH-USD"], limit=10)
    h = s.calls[0]["headers"]
    assert h["X-Revx-API-Key"] == "K" * 64 and h["X-Revx-Timestamp"] == "1765360896219"
    assert s.calls[0]["url"].endswith("/api/1.0/orders/active?symbols=BTC-USD,ETH-USD&limit=10")
    msg = b"1765360896219GET/api/1.0/orders/activesymbols=BTC-USD,ETH-USD&limit=10"
    key.public_key().verify(base64.b64decode(h["X-Revx-Signature"]), msg)


def test_place_market_order_body_signed(key):
    s = FakeSession({("POST", "/api/1.0/orders"): Resp(200, {"data": [{"venue_order_id": "v1", "state": "new"}]})})
    c = RevolutXClient("K" * 64, key, session=s, clock=lambda: 1.0, sleep=lambda x: None)
    c.place_order("BTC-USD", "BUY", base_size=Decimal("0.0012"), client_order_id="cid")
    call = s.calls[0]; body = call["data"].decode()
    assert json.loads(body) == {"client_order_id": "cid", "symbol": "BTC-USD", "side": "buy",
                                "order_configuration": {"market": {"base_size": "0.0012"}}}
    assert " " not in body
    key.public_key().verify(base64.b64decode(call["headers"]["X-Revx-Signature"]), b"1000POST/api/1.0/orders" + body.encode())
    with pytest.raises(ValueError):
        c.place_order("BTC-USD", "buy", base_size="1", quote_size="1")


def test_limit_post_only(key):
    s = FakeSession({("POST", "/orders"): Resp(200, {"data": [{}]})})
    c = RevolutXClient("K" * 64, key, session=s, sleep=lambda x: None)
    c.place_order("ETH-EUR", "sell", quote_size="50", limit_price="2000.5", post_only=True, client_order_id="x")
    assert json.loads(s.calls[0]["data"])["order_configuration"] == {
        "limit": {"quote_size": "50", "price": "2000.5", "execution_instructions": ["post_only"]}}


def test_429_retry_after_ms(key):
    slept = []
    s = FakeSession({("GET", "/balances"): [Resp(429, {"message": "x"}, {"Retry-After": "250"}), Resp(200, [])]})
    c = RevolutXClient("K" * 64, key, session=s, sleep=slept.append)
    assert c.balances() == [] and 0.25 in slept


def test_error_raised(key):
    s = FakeSession({("DELETE", "/orders/abc"): Resp(404, {"message": "not found"})})
    c = RevolutXClient("K" * 64, key, session=s, sleep=lambda x: None)
    with pytest.raises(RevolutXError) as e:
        c.cancel_order("abc")
    assert e.value.status == 404


def test_cancel_204(key):
    s = FakeSession({("DELETE", "/orders"): Resp(204, None)})
    assert RevolutXClient("K" * 64, key, session=s, sleep=lambda x: None).cancel_all() is None


def test_public_no_auth_headers():
    s = FakeSession({("GET", "/public/configuration/pairs"): Resp(200, {"BTC/USD": {
        "base": "BTC", "quote": "USD", "base_step": "0.0000001", "quote_step": "0.01", "min_order_size": "0.0000001",
        "max_order_size": "1000", "min_order_size_quote": "0.01", "status": "active"}})})
    r = pairs_to_rules(RevolutXClient(session=s, sleep=lambda x: None).public_pairs())
    assert "X-Revx-Signature" not in s.calls[0]["headers"] and "BTC-USD" in r


def test_quantize_rules():
    r = PairRules(Decimal("0.0001"), Decimal("0.01"), Decimal("0.001"), Decimal("10"), Decimal("5"))
    assert r.quantize_base(0.12345678, 100) == Decimal("0.1234")
    assert r.quantize_base(0.0009, 100000) == 0        # < min_order_size
    assert r.quantize_base(0.002, 100) == 0            # 0.2 < min quote 5
    assert r.quantize_base(50, 100) == Decimal("10")   # max_order_size
    assert r.quantize_price(123.456) == Decimal("123.45")


def test_dry_run_forces_paper():
    assert isinstance(make_broker(Config(broker="revolutx", dry_run=True)), PaperBroker)


def test_revolutx_broker_flow(key, tmp_path):
    rules = {"BTC-USD": PairRules(Decimal("0.00001"), Decimal("0.01"), Decimal("0.00001"), Decimal("100"), Decimal("1"))}
    s = FakeSession({
        ("POST", "/orders"): Resp(200, {"data": [{"venue_order_id": "v1", "state": "new"}]}),
        ("GET", "/balances"): Resp(200, [{"currency": "USD", "available": "900", "reserved": "0", "total": "900"},
                                         {"currency": "BTC", "available": "0.00123", "reserved": "0", "total": "0.00123"},
                                         {"currency": "ETH", "available": "1", "reserved": "0", "total": "1"}]),
    })
    c = RevolutXClient("K" * 64, key, session=s, sleep=lambda x: None)
    b = RevolutXBroker(c, "USD", rules, str(tmp_path / "st.json"))
    from bot.brokers.base import Order
    res = b.submit(Order("BTC-USD", "BUY", 0.0012345, "MARKET", stop_price=70000), 80000)
    assert res["status"] == "SUBMITTED"
    assert json.loads(s.calls[0]["data"])["order_configuration"]["market"]["base_size"] == "0.00123"
    pos = b.positions()
    assert set(pos) == {"BTC-USD"} and pos["BTC-USD"].entry == 80000 and pos["BTC-USD"].atr_stop == 70000
    assert b.cash() == 900
    assert b.equity({"BTC-USD": 80000}) == pytest.approx(900 + 0.00123 * 80000)


def test_ev_cost_uses_taker_fee():
    c = Config()
    assert c.transaction_cost_frac == pytest.approx(2 * (0.0009 + 0.001))
