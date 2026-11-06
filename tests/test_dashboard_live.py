"""Painel ao vivo (/live, /api/live): JSON dos 4 bots paper, Basic Auth, e garantia de que não há rotas que mudem estado."""
import base64, inspect, json, re, threading, urllib.request, urllib.error
import pytest
from bot import dashboard as dash
from bot.dashboard import make_handler, State, load_auth
from bot.config import Config
from bot import live_view as LV

BOTS = {"D_executor", "A_c3", "A_c3_raw", "B_bh_btc"}


class FakePub:
    def __init__(self, fail=False): self.fail, self.calls = fail, 0
    def public_tickers(self, syms, region=None):
        self.calls += 1
        if self.fail: raise RuntimeError("HTTP 502 Bad Gateway from /home/box/secret/path")
        return [{"symbol": s.replace("-", "/"), "bid": "99", "ask": "101", "mid": "100", "last_price": "100", "price_change_24h": "1"} for s in syms]


def _serve(st, auth=None):
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st, auth)); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


def _get(url, auth=None, method="GET"):
    rq = urllib.request.Request(url, method=method, data=b"{}" if method != "GET" else None)
    if auth: rq.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    return urllib.request.urlopen(rq, timeout=20)


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.delenv("REVX_API_KEY", raising=False)
    st = State(Config(log_dir=str(tmp_path)))
    st.live_prices = LV.Prices(FakePub(), None)
    st.marks = LV.Marks(str(tmp_path / "marks.jsonl"), every=0)
    return st


def test_api_live_has_all_four_bots(state):
    srv, base = _serve(state, ("paper", "pw-test"))
    try:
        d = json.load(_get(base + "/api/live", ("paper", "pw-test")))
    finally:
        srv.shutdown()
    assert d["simulated"] is True and d["live_orders"] is False and "SIMULADO" in d["banner"]
    keys = {b["key"] for b in d["bots"]}
    assert BOTS <= keys and all(k.startswith("S_") for k in keys - BOTS)   # + cartões Scalp (paper) quando existem
    for b in d["bots"]:
        if not b["available"]: continue
        for k in ("equity", "pnl", "drawdown", "to_ceiling", "positions", "recent", "criteria", "last_run", "curve"):
            assert k in b, (b["key"], k)
        assert b["ceiling"] == d["ceiling"]
        assert all(set(p) >= {"coin", "entry", "stop", "tp", "price", "unrealized"} for p in b["positions"])
        ts = [t for t, _ in b["curve"]]; assert ts == sorted(set(ts))           # Lightweight Charts: tempos únicos crescentes
    assert {"n", "win_rate", "expectancy_r", "max_dd", "thresholds"} <= set(d["desk"])
    blob = json.dumps(d)
    assert not re.search(r"REVX_API_KEY|private\.pem|revx-keys|BEGIN .*PRIVATE", blob)


def test_basic_auth_required(state):
    srv, base = _serve(state, ("paper", "pw-test"))
    try:
        for p in ("/", "/live", "/api/live", "/api/state", "/classic"):
            with pytest.raises(urllib.error.HTTPError) as e: _get(base + p)
            assert e.value.code == 401 and "Basic" in e.value.headers.get("WWW-Authenticate", "")
        with pytest.raises(urllib.error.HTTPError) as e: _get(base + "/api/live", ("paper", "wrong"))
        assert e.value.code == 401
        assert _get(base + "/healthz").read() == b"ok"                         # sem dados, só para o watchdog
        r = _get(base + "/", ("paper", "pw-test"))
        html = r.read().decode()
        assert r.status == 200 and "SIMULADO — nenhuma ordem real" in html and r.headers["X-Frame-Options"] == "DENY"
    finally:
        srv.shutdown()


def test_no_mutating_routes(state):
    srv, base = _serve(state, ("paper", "pw-test"))
    try:
        for m in ("POST", "PUT", "DELETE", "PATCH"):
            for p in ("/api/live", "/api/rebase", "/api/resume", "/api/unkill", "/api/order", "/"):
                with pytest.raises(urllib.error.HTTPError) as e: _get(base + p, ("paper", "pw-test"), m)
                assert e.value.code == 405
        for p in ("/api/rebase", "/api/resume", "/api/unkill", "/api/kill", "/api/order", "/api/orders", "/api/cancel"):
            with pytest.raises(urllib.error.HTTPError) as e: _get(base + p, ("paper", "pw-test"))
            assert e.value.code == 404
    finally:
        srv.shutdown()
    src = inspect.getsource(dash.make_handler) + inspect.getsource(LV)
    for bad in ("rebase(", "resume(", "unkill", "place_order", "cancel_order", "market_sell", "tpsl", "save_state(", "run_once("):
        assert bad not in src, bad
    for r in dash.GET_ROUTES:
        assert not re.search(r"rebase|resume|unkill|kill|order|cancel", r)
    js = open(dash.os.path.join(dash.STATIC, "live.js")).read()
    assert "method:" not in js and "POST" not in js and "<button" not in open(dash.os.path.join(dash.STATIC, "live.html")).read()


def test_prices_cache_and_502_fallback():
    t = [1000.0]; pub = FakePub(); P = LV.Prices(pub, None, ttl=20, clock=lambda: t[0])
    a = P.get(["BTC-USD"]); P.get(["BTC-USD"]); assert pub.calls == 1 and a["px"]["BTC-USD"]["mid"] == 100 and not a["stale"]
    pub.fail = True; t[0] += 30
    b = P.get(["BTC-USD"])
    assert pub.calls == 2 and b["px"]["BTC-USD"]["mid"] == 100 and b["stale"] and "502" in b["error"] and "/home" not in b["error"]
    P.get(["BTC-USD"]); assert pub.calls == 2                                  # sem martelar a API durante a falha (ttl)


def test_load_auth_from_file(tmp_path):
    f = tmp_path / "pw"; f.write_text("s3cret\n")
    assert load_auth({"DASHBOARD_PASSWORD_FILE": str(f)}) == ("paper", "s3cret")
    assert load_auth({"DASHBOARD_PASSWORD": "x", "DASHBOARD_USER": "u"}) == ("u", "x")
    assert load_auth({"DASHBOARD_PASSWORD_FILE": str(tmp_path / "missing")}) is None


def test_london_time():
    assert LV.london("2026-10-20T15:13:25Z") == "20/10 16:13"
    assert LV.london(1792509205029) == "20/10 16:13"
