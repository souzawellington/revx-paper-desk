import json, threading, urllib.request, urllib.error
import pytest
from bot.dashboard import ReadOnlyClient, paper_state, make_handler, State
from bot.revolutx.client import RevolutXClient
from bot.variants import resample, simulate, Variant
from bot.config import Config


class S:
    def __init__(self): self.calls = []
    def request(self, *a, **k): self.calls.append(a); raise AssertionError("não devia chegar à rede")


def test_readonly_blocks_writes():
    ro = ReadOnlyClient(RevolutXClient(session=S()))
    for name in ("place_order", "cancel_order", "cancel_all"):
        with pytest.raises(PermissionError):
            getattr(ro, name)
    with pytest.raises(PermissionError):
        ro._c._request("POST", "/orders", body={})
    with pytest.raises(PermissionError):
        ro._c.place_order("BTC-USD", "buy", base_size="1")


def test_paper_state_from_audit():
    ev = [{"event": "order", "ts": 1, "order": {"ticker": "BTC-USD", "side": "BUY", "qty": 2, "stop_price": 90}, "result": {"status": "FILLED", "price": 100}},
          {"event": "order", "ts": 2, "order": {"ticker": "BTC-USD", "side": "SELL", "qty": 1}, "result": {"status": "FILLED", "price": 110}}]
    s = paper_state(ev)
    assert s["positions"]["BTC-USD"]["qty"] == 1 and s["positions"]["BTC-USD"]["stop"] == 90 and len(s["orders"]) == 2


def test_http_post_rejected(monkeypatch, tmp_path):
    from http.server import ThreadingHTTPServer
    monkeypatch.delenv("REVX_API_KEY", raising=False)
    st = State(Config(log_dir=str(tmp_path)))
    st.prices = lambda: {}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st)); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/state", data=b"{}", method="POST"))
        assert e.value.code == 405
        s = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state"))
        assert s["account"]["source"].startswith("paper") and s["cycles"] == []
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/").status == 200
    finally:
        srv.shutdown()


def test_resample_4h_complete_blocks():
    c = [{"start": i * 3_600_000, "open": i, "high": i + 1, "low": i - 1, "close": i + .5, "volume": 1} for i in range(10)]
    r = resample(c, 4)
    assert len(r) == 2 and r[0]["open"] == 0 and r[0]["close"] == 3.5 and r[0]["high"] == 4 and r[0]["volume"] == 4


def test_variant_tp_hits():
    cfg = Config()
    closes = [100 + i * .5 for i in range(60)] + [200]
    c = [{"start": i * 3_600_000, "open": x, "high": x * 1.005, "low": x * .995, "close": x, "volume": 1} for i, x in enumerate(closes)]
    tr = simulate(c, cfg, Variant("t", take_profit_r=2))
    assert tr and tr[-1]["why"] == "TP"
