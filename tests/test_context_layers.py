"""OpenBB/yfinance (macro), FinanceToolkit (métricas), Riskfolio (HRP), TradingAgents (debate) e dashboard
Lightweight Charts. Tudo offline; todas as camadas só vetam/reduzem; dashboard só-leitura."""
import json, math, os, threading, urllib.request, urllib.error
import pytest
from desk.rules import load_rules, Rules
from desk import macro as M, metrics as ME, allocation as A, debate as DB, store, replay, run as desk_run
from tests.test_desk import path_hours, FakeClient, T0, H, D, desk_state

DAY = 86_400_000


def rules_with(**kw):
    r = load_rules(); return Rules({**r.p, **kw})


def mk_ctx(n=80, spx=None, vix=None, dxy=None, tnx=None, start="2026-01-01"):
    from datetime import datetime, timedelta
    d0 = datetime.strptime(start, "%Y-%m-%d"); dates = [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    def ser(vals): return {"date": dates, "close": vals, "day": [M._day_ms(x) for x in dates], "provider": "test"}
    ctx = {}
    for k, v in (("spx", spx), ("vix", vix), ("dxy", dxy), ("us10y", tnx)):
        if v is not None: ctx[k] = ser(v if isinstance(v, list) else [v] * n)
    return ctx, dates


# ---------------- macro ----------------
def test_macro_flags_and_veto_threshold():
    n = 80
    ctx, dates = mk_ctx(n, spx=[100 - i * 0.5 for i in range(n)], vix=30.0, dxy=[100 + i * 0.2 for i in range(n)], tnx=4.0)
    now = M._day_ms(dates[-1]) + DAY + 2 * H
    m = M.evaluate(ctx, now, load_rules())
    assert set(m["flags"]) == {"EQ_DOWN", "VOL_STRESS", "USD_UP"} and m["status"] == M.RISK_OFF and m["action"] == "VETO"
    calm, _ = mk_ctx(n, spx=[100 + i for i in range(n)], vix=14.0, dxy=100.0, tnx=4.0)
    assert M.evaluate(calm, now, load_rules())["status"] == M.OK
    one, _ = mk_ctx(n, spx=[100 + i for i in range(n)], vix=30.0, dxy=100.0, tnx=4.0)
    assert M.evaluate(one, now, load_rules())["status"] == M.CAUTION
    assert M.evaluate(one, now, rules_with(macro_veto_flags=1))["action"] == "VETO"


def test_macro_point_in_time_no_lookahead():
    n = 80
    vals = [14.0] * (n - 1) + [80.0]          # pico de VIX só na última vela
    ctx, dates = mk_ctx(n, spx=[100 + i for i in range(n)], vix=vals, dxy=100.0, tnx=4.0)
    last = M._day_ms(dates[-1])
    before = M.evaluate(ctx, last + DAY + 0.5 * H, load_rules())   # ainda antes de D+1 00:00 + 1h
    after = M.evaluate(ctx, last + DAY + 1 * H, load_rules())
    assert before["series"]["vix"]["value"] == 14.0 and after["series"]["vix"]["value"] == 80.0


def test_macro_insufficient_and_stale():
    n = 80
    ctx, dates = mk_ctx(n, spx=[100 + i for i in range(n)], vix=14.0)   # só 2 séries < macro_min_series
    now = M._day_ms(dates[-1]) + DAY + 2 * H
    assert M.evaluate(ctx, now, load_rules())["status"] == M.ABST
    full, _ = mk_ctx(n, spx=[100 + i for i in range(n)], vix=14.0, dxy=100.0, tnx=4.0)
    assert M.evaluate(full, now + 10 * DAY, load_rules())["status"] == M.ABST   # desatualizado
    assert M.evaluate({}, now, load_rules())["action"] == "NO_OPINION"
    assert M.evaluate(None, now, load_rules())["size_mult"] == 1.0


def test_macro_cache_roundtrip_and_compare(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    M.save("vix", [{"date": "2026-01-02", "close": 20.0}, {"date": "2026-01-01", "close": 19.0}], "yfinance", "^VIX", str(a))
    M.save("vix", [{"date": "2026-01-01", "close": 19.0}], "openbb", "VIX", str(b))
    ctx = M.load(str(a)); assert ctx["vix"]["date"] == ["2026-01-01", "2026-01-02"]
    c = M.compare(str(a), str(b), ("vix",)); assert c["vix"]["common_days"] == 1 and c["vix"]["only_a"] == 1 and c["vix"]["median_dev"] == 0


def test_macro_live_decision_offline_is_safe(tmp_path):
    m = M.live_decision(load_rules(), 1_800_000_000_000, data_dir=str(tmp_path), log=lambda *a: None)
    assert m["status"] == M.ABST and m["size_mult"] == 1.0   # fetch está bloqueado no conftest


def test_replay_macro_enforce_only_removes_trades(tmp_path):
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir(); (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    first = min(c["start"] for c in h1)
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(first / 1000 - 200 * 86400, timezone.utc).strftime("%Y-%m-%d")
    n = 400
    storm, _ = mk_ctx(n, spx=[100 - i * 0.1 for i in range(n)], vix=40.0, dxy=100.0, tnx=4.0, start=start)
    off = replay.run(["TST-USD"], rules_with(macro_mode="off", no_hero=False), str(d))
    sh = replay.run(["TST-USD"], rules_with(macro_mode="shadow", no_hero=False), str(d), macro_ctx=storm)
    en = replay.run(["TST-USD"], rules_with(macro_mode="enforce", no_hero=False), str(d), macro_ctx=storm)
    assert [t["net_r"] for t in off["trades"]] == [t["net_r"] for t in sh["trades"]]
    assert off["trades"] and all(t["macro"]["status"] == M.RISK_OFF for t in sh["trades"])
    assert en["trades"] == [] and replay.score(en, rules_with())["macro_vetoes"] >= 1


# ---------------- métricas (FinanceToolkit) ----------------
def test_metrics_known_values():
    rs = [2.0, -1.0, -1.0, 3.0, -1.0]
    m = ME.trade_metrics(rs)
    assert m["profit_factor"] == pytest.approx(5 / 3) and m["omega_r"] == pytest.approx(5 / 3)
    assert m["sortino_r"] == pytest.approx(0.4 / math.sqrt(3 / 5))
    assert ME.quantile([1, 2, 3, 4], 0.5) == 2.5
    v, cv = ME.var_cvar([-3, -2, -1, 0, 1, 2, 3, 4, 5, 6], 0.1)
    assert v == pytest.approx(-2.1) and cv == -3
    c = ME.curve_metrics([100, 110, 99, 120])
    assert c["max_dd"] == pytest.approx(0.1) and c["max_dd_days"] == 1 and c["total_return"] == pytest.approx(0.2)
    assert ME.trade_metrics([]) == {"n": 0} and ME.curve_metrics([1]) == {"days": 1}


def test_auditor_stats_has_descriptive_metrics_go_unchanged(desk_state):
    from desk.auditor import stats
    r = load_rules(); s = stats(r)
    assert s["metrics"] == {"n": 0} and s["go"] is False and set(s["thresholds"]) == {"trades", "win_rate", "expectancy_r", "max_dd"}


# ---------------- HRP (Riskfolio) ----------------
def bars_from_rets(rets, start=0):
    px, out = 100.0, [{"start": start, "open": 100, "high": 100, "low": 100, "close": 100.0}]
    for i, r in enumerate(rets, 1):
        px *= 1 + r; out.append({"start": start + i * DAY, "open": px, "high": px, "low": px, "close": px})
    return out


def test_hrp_two_assets_inverse_variance():
    import random
    rnd = random.Random(1); a = [rnd.gauss(0, 0.01) for _ in range(90)]; b = [rnd.gauss(0, 0.03) for _ in range(90)]
    w = A.hrp_weights([a, b]); va, vb = A.cov(a, a), A.cov(b, b)
    assert w[0] == pytest.approx((1 / va) / (1 / va + 1 / vb)) and sum(w) == pytest.approx(1)


def test_hrp_cap_only_reduces_and_no_positions_no_effect():
    import random
    rnd = random.Random(2); r = load_rules()
    calm = bars_from_rets([rnd.gauss(0, 0.01) for _ in range(90)]); wild = bars_from_rets([rnd.gauss(0, 0.06) for _ in range(90)])
    d0 = A.decision("X-USD", wild, {}, r); assert d0["status"] == A.ABST and d0["cap_frac"] == r.max_position_frac
    d = A.decision("X-USD", wild, {"Y-USD": calm}, r)
    assert d["status"] == A.OK and d["cap_frac"] < r.max_position_frac
    d2 = A.decision("Y-USD", calm, {"X-USD": wild}, r); assert d2["cap_frac"] == pytest.approx(r.max_position_frac)   # nunca > 15%
    en = rules_with(alloc_mode="enforce")
    assert A.apply(10.0, 100.0, 10_000, d, r) == 10.0                      # shadow: sem efeito
    q = A.apply(10.0, 100.0, 10_000, d, en); assert q <= 10.0 and q == pytest.approx(min(10.0, d["cap_frac"] * 100))
    assert A.apply(1.0, 100.0, 10_000, d, en) == 1.0                         # já abaixo do teto: não aumenta
    short = A.decision("X-USD", wild[:10], {"Y-USD": calm[:10]}, r); assert short["status"] == A.ABST


def test_cvar_hist_matches_riskfolio_formula():
    x = [-0.05, -0.02, 0.0, 0.01, 0.03] * 4
    s = sorted(x); idx = math.ceil(0.05 * len(s)) - 1
    assert A.cvar_hist(x, 0.05) == pytest.approx(-s[idx] - sum(s[i] - s[idx] for i in range(idx + 1)) / (0.05 * len(s)))


def test_replay_alloc_enforce_never_enlarges(tmp_path):
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir(); (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    off = replay.run(["TST-USD"], rules_with(alloc_mode="off", macro_mode="off", no_hero=False), str(d))
    en = replay.run(["TST-USD"], rules_with(alloc_mode="enforce", macro_mode="off", no_hero=False), str(d))
    assert off["trades"] and len(en["trades"]) == len(off["trades"])
    for a, b in zip(en["trades"], off["trades"]): assert a["qty"] <= b["qty"] + 1e-9 and a["net_r"] == b["net_r"]


# ---------------- debate (TradingAgents) ----------------
def test_debate_never_enlarges_and_reflects_layers():
    r = load_rules()
    plan = {"plan_id": "P1", "entry": 100, "stop": 97,
            "panel": json.dumps({"action": "REDUCE", "size_mult": 0.5, "votes": [{"analyst": "trend_4h", "signal": "bearish", "confidence": 0.4, "metrics": {}},
                                                                                 {"analyst": "momentum_1d", "signal": "bullish", "confidence": 0.6, "metrics": {}}]}),
            "macro": json.dumps({"status": "RISK_OFF", "flags": ["EQ_DOWN", "VOL_STRESS"], "size_mult": 0.0}), "prot": "", "alloc": ""}
    rec = DB.record(plan, r)
    assert rec["would"] == "VETO" and all(v <= 1.0 for v in rec["risk_views"].values()) and rec["risk_views"]["aggressive"] == 1.0
    assert any("macro" in b for b in rec["bear"]) and any("momentum_1d" in b for b in rec["bull"])
    clean = DB.record({"plan_id": "P2", "entry": 100, "stop": 97}, r); assert clean["would"] == "KEEP"
    assert r.debate_record is False


def test_debate_settle_memory():
    r = load_rules()
    plans = [{"plan_id": f"P{i}", "entry": 100, "stop": 97, "panel": json.dumps({"action": "VETO" if i < 5 else "KEEP", "size_mult": 0 if i < 5 else 1, "votes": []}),
              "macro": "", "prot": "", "alloc": ""} for i in range(10)]
    journal = [{"trade_id": f"P{i}", "line": "RESULT", "r": "-1" if i < 5 else "2", "mode": "PAPER"} for i in range(10)]
    out = DB.settle(r, plans, journal)
    assert out["settled"] == 10 and out["layers"]["panel"]["VETO"]["mean_r"] == -1 and "acertou" in out["lessons"][0]


def test_pipeline_records_macro_and_alloc_in_plan(desk_state):
    rules = load_rules(); cli = FakeClient(path_hours())
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    p = store.read("trade_plan.csv")[0]
    assert json.loads(p["macro"])["mode"] == "shadow" and json.loads(p["alloc"])["status"] == A.ABST   # sem posições abertas
    ob = [a for a in store.outbox() if a["type"] == "ENTRY_ALERT"][0]
    assert "macro" in ob["data"] and "alloc" in ob["data"] and ob["data"]["debate"] is None and "Macro (shadow)" in ob["text"]


def test_new_layers_have_no_order_paths():
    for f in ("desk/macro.py", "desk/allocation.py", "desk/debate.py", "desk/metrics.py"):
        src = open(f).read()
        for bad in ("place_order", "create_order", "requests.post", "cancel_order", "anthropic", "openai", "REVX_API_KEY"):
            assert bad not in src, (f, bad)


# ---------------- dashboard (Lightweight Charts) ----------------
def test_dashboard_vendored_lwc_and_readonly(monkeypatch, tmp_path, desk_state):
    from http.server import ThreadingHTTPServer
    from bot.dashboard import make_handler, State
    from bot.config import Config
    monkeypatch.delenv("REVX_API_KEY", raising=False)
    store.write("zones.csv", [{"coin": "TST-USD", "zone_id": "TST-USD:1", "rank": 1, "zone_top": 11, "zone_bottom": 10, "status": "TESTED",
                               "formed_ts": 0, "tested_ts": 4 * H, "confirm_ts": ""}])
    store.write("positions.csv", [{"pid": "P-T", "plan_id": "P-T", "coin": "TST-USD", "status": "CLOSED", "entry": 11, "stop": 10.5,
                                   "initial_stop": 10.5, "tp_price": 13, "qty": 1, "opened_ts": 8 * H, "exit": 13, "exit_ts": 16 * H, "exit_rule": "TAKE_PROFIT"}])
    os.makedirs(os.path.join(str(desk_state), "cache"), exist_ok=True)
    json.dump([{"start": i * 4 * H, "open": 10, "high": 12, "low": 9.5, "close": 11, "volume": 1} for i in range(10)],
              open(os.path.join(str(desk_state), "cache", "TST-USD_240.json"), "w"))
    st = State(Config(log_dir=str(tmp_path))); st.prices = lambda: {}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st)); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        html = urllib.request.urlopen(base + "/").read().decode()
        assert "cdn.jsdelivr" not in html and "/vendor/lightweight-charts.standalone.production.js" in html and "tradingview.com" in html
        js = urllib.request.urlopen(base + "/vendor/lightweight-charts.standalone.production.js").read()
        assert b"Lightweight Charts" in js[:400] and len(js) > 100_000
        assert b"TradingView" in urllib.request.urlopen(base + "/vendor/NOTICE-lightweight-charts.txt").read()
        assert "TST-USD" in json.load(urllib.request.urlopen(base + "/api/desk/coins"))
        c = json.load(urllib.request.urlopen(base + "/api/desk/chart?coin=TST-USD&tf=240"))
        assert len(c["candles"]) == 10 and c["zones"][0]["status"] == "TESTED" and c["trades"][0]["tp"] == 13
        assert c["candles"][1]["time"] - c["candles"][0]["time"] == 4 * 3600
        e = json.load(urllib.request.urlopen(base + "/api/desk/equity")); assert "paper" in e and "replay" in e
        for bad in ("/api/desk/chart?coin=../../etc", "/api/desk/chart?coin=NOPE-USD"):
            with pytest.raises(urllib.error.HTTPError) as ex: urllib.request.urlopen(base + bad)
            assert ex.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as ex: urllib.request.urlopen(base + "/vendor/../dashboard.py")
        assert ex.value.code == 404
        for m in ("POST", "PUT", "DELETE"):
            with pytest.raises(urllib.error.HTTPError) as ex:
                urllib.request.urlopen(urllib.request.Request(base + "/api/desk/chart", data=b"{}", method=m))
            assert ex.value.code == 405
    finally:
        srv.shutdown()
