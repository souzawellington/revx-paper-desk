"""CCXT só público: recusa credenciais, só métodos de dados, paginação, qualidade, sanity cross-venue."""
import json, types
import pytest
from desk import ccxt_data as C, risk_officer, store
from desk.rules import load_rules, Rules

H = C.H


class FakeEx:
    rateLimit = 10
    def __init__(self, cfg): self.cfg = cfg; self.apiKey = cfg.get("apiKey"); self.secret = None; self.calls = 0; self.markets = {"BTC/USD": {}}
    def load_markets(self): return self.markets
    def fetch_ohlcv(self, sym, tf, since=None, limit=300):
        self.calls += 1; start = max(since, 10 * H)
        return [[t, 1, 2, 0.5, 1.5, 3] for t in range(start, min(start + limit * H, 60 * H), H)]
    def fetch_ticker(self, sym): return {"last": 100.0}
    def create_order(self, *a, **k): raise AssertionError("nunca")
    def fetch_balance(self, *a, **k): raise AssertionError("nunca")


fake_mod = types.SimpleNamespace(coinbase=FakeEx, kraken=FakeEx, bitstamp=FakeEx)


def test_refuses_credentials_and_private_methods():
    with pytest.raises(ValueError): C.PublicOnly("coinbase", {"apiKey": "x"}, ccxt_mod=fake_mod)
    with pytest.raises(ValueError): C.PublicOnly("coinbase", {"secret": "x"}, ccxt_mod=fake_mod)
    ex = C.PublicOnly("coinbase", ccxt_mod=fake_mod)
    assert ex._ex.cfg["enableRateLimit"] is True
    for m in ("create_order", "fetch_balance", "cancel_order", "fetch_my_trades", "withdraw"):
        with pytest.raises(AttributeError): getattr(ex, m)


def test_pagination_closed_bars_and_quality():
    ex = C.PublicOnly("coinbase", ccxt_mod=fake_mod)
    rows = C.fetch_hourly(ex, "BTC/USD", 0, 50 * H, page=7, log=lambda *a: None)
    assert rows[0]["start"] == 10 * H and rows[-1]["start"] == 49 * H     # só fechadas (start+1h<=until)
    assert len({r["start"] for r in rows}) == len(rows)
    q = C.quality(rows); assert q["gaps"] == 0 and q["invalid_bars"] == 0 and q["bars"] == 40
    bad = rows[:3] + rows[5:]; bad[0] = {**bad[0], "low": 5}
    q2 = C.quality(bad); assert q2["missing_bars"] == 2 and q2["invalid_bars"] == 1


def test_cross_venue_check():
    assert C.cross_venue_check(100, {"a": 100.5, "b": 99.8})["status"] == "OK"
    d = C.cross_venue_check(110, {"a": 100, "b": 101, "c": 99}); assert d["status"] == "DEVIATION" and d["dev"] == pytest.approx(0.1)
    assert C.cross_venue_check(100, {"a": None})["status"] == "INSUFFICIENT_DATA"
    assert C.cross_venue_check(None, {"a": 100})["status"] == "INSUFFICIENT_DATA"


def test_live_sanity_with_fake_venues():
    import importlib; mod = importlib.reload(C)   # conftest substitui live_sanity; recarregar dá a versão real
    r = mod.live_sanity("BTC-USD", 103.0, ("coinbase", "kraken"), 0.02, ccxt_mod=fake_mod)
    assert r["status"] == "DEVIATION" and r["venues"] == 2
    r = mod.live_sanity("BTC-USD", 100.5, ("coinbase",), 0.02, ccxt_mod=fake_mod); assert r["status"] == "OK"
    broken = types.SimpleNamespace()
    assert mod.live_sanity("BTC-USD", 100.0, ("nope",), ccxt_mod=broken)["status"] == "INSUFFICIENT_DATA"


def test_risk_officer_xvenue_reason(monkeypatch):
    rules = Rules({**load_rules().p})
    monkeypatch.setattr(C, "live_sanity", lambda *a, **k: {"status": "DEVIATION", "dev": 0.05, "median": 1, "venues": 2})
    xv = risk_officer.xvenue("BTC-USD", {"mid": "105"}, rules, log=lambda *a: None)
    assert xv["status"] == "DEVIATION"
    monkeypatch.setattr(C, "live_sanity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rede")))
    assert risk_officer.xvenue("BTC-USD", None, rules, log=lambda *a: None)["status"] == "INSUFFICIENT_DATA"


def test_desk_live_roles_never_import_ccxt_for_orders():
    for f in ("desk/ccxt_data.py", "desk/risk_officer.py", "desk/gate.py"):
        src = open(f).read()
        for bad in (".create_order(", ".fetch_balance(", ".cancel_order(", "\"apiKey\":"):
            assert bad not in src, (f, bad)


def test_compare_series():
    a = [{"start": i * H, "close": 100.0} for i in range(10)]
    b = [{"start": i * H, "close": 100.0 if i != 3 else 110.0} for i in range(12)]
    r = C.compare_series(a, b); assert r["common_bars"] == 10 and r["bars_over"] == 1
    assert C.compare_series(a, [])["status"] == "INSUFFICIENT_DATA"
