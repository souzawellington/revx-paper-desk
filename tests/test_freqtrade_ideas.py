"""Ideias freqtrade re-implementadas: protections/filtros (veto-only), rigor lookahead/recursive, estratégias comunidade."""
import json, math
import pytest
from desk.rules import load_rules, Rules
from desk import protections as P, replay, community, analysis, store, run as desk_run
from tests.test_desk import path_hours, FakeClient, T0, H, D, desk_state


def R(**kw): r = load_rules(); return Rules({**r.p, **kw})


def tr(sym, ts, r, why="STOP", pnl=None): return {"symbol": sym, "exit_ts": ts, "net_r": r, "why": why, "pnl": pnl if pnl is not None else r * 100}


def test_defaults_shadow_and_never_place_orders():
    r = load_rules(); assert r.protections_mode == "shadow" and r.panel_mode == "shadow"
    src = open("desk/protections.py").read() + open("desk/community.py").read() + open("desk/analysis.py").read()
    for bad in ("place_order", "create_order", "requests.post", "ccxt", "freqtrade."): assert bad not in src


def test_cooldown_per_pair():
    r = R(); now = 100 * H
    lk = P.locks([tr("A", now - 2 * H, 1.0, "TAKE_PROFIT")], now, 10_000, r)
    assert "COOLDOWN" in P.blocked("A", lk) and P.blocked("B", lk) == []
    assert P.blocked("A", P.locks([tr("A", now - 5 * H, 1.0, "TAKE_PROFIT")], now, 10_000, r)) == []


def test_stoploss_guard_global_and_expires():
    r = R(); now = 100 * H
    t = [tr(f"C{i}", now - (3 - i) * H, -1.0) for i in range(4)]
    assert any("STOPLOSS_GUARD" in x for x in P.locks(t, now, 1e9, r)["global"])
    assert not P.locks(t, now + 6 * H, 1e9, r)["global"]             # lock 4h expirou
    assert not P.locks(t[:3], now, 1e9, r)["global"]                 # só 3 stops


def test_max_drawdown_global():
    r = R(); now = 1000 * H
    t = [tr(f"C{i}", now - (10 - i) * H, -1.0, "ANCHOR_1D_CLOSE", pnl=-120) for i in range(5)]
    g = P.locks(t, now, 10_000, R(prot_cooldown_hours=0))["global"]
    assert any("MAX_DRAWDOWN" in x for x in g)                       # 600/10000 = 6% > 5%
    assert not any("MAX_DRAWDOWN" in x for x in P.locks(t, now, 100_000, r)["global"])


def test_low_profit_pair():
    r = R(); now = 1000 * H
    t = [tr("X", now - 100 * H, -1.0, "ANCHOR_1D_CLOSE"), tr("X", now - 50 * H, 0.5, "TAKE_PROFIT")]
    assert any("LOW_PROFIT" in x for x in P.blocked("X", P.locks(t, now, 1e9, r)))
    t2 = [tr("X", now - 100 * H, -1.0, "ANCHOR_1D_CLOSE"), tr("X", now - 50 * H, 3.0, "TAKE_PROFIT")]
    assert not any("LOW_PROFIT" in x for x in P.blocked("X", P.locks(t2, now, 1e9, r)))


def test_future_trades_ignored():
    r = R(); now = 100 * H
    assert P.locks([tr("A", now + H, -1.0)] * 5, now, 1e9, r) == {"global": [], "pairs": {}}


def d1(n, px=10.0, vol=1e5, wiggle=0.02):
    return [{"start": i * D, "open": px, "high": px * 1.03, "low": px * 0.97, "close": px * (1 + (wiggle if i % 2 else -wiggle)), "volume": vol} for i in range(n)]


def test_pair_filters_and_insufficient_data():
    r = R()
    ok = P.pair_filters(d1(60), r, {"bid": "9.99", "ask": "10.0"}); assert ok["reasons"] == []
    assert any("AGE_FILTER" in x for x in P.pair_filters(d1(10), r)["reasons"])
    assert any("VOLUME_FILTER" in x for x in P.pair_filters(d1(60, vol=10), r)["reasons"])
    assert any("VOLATILITY_FILTER" in x for x in P.pair_filters(d1(60, wiggle=0.0), r)["reasons"])
    assert any("SPREAD_FILTER" in x for x in P.pair_filters(d1(60), r, {"bid": "9", "ask": "10"})["reasons"])
    nd = P.pair_filters(d1(60), r, None); assert nd["checks"]["spread"] == "INSUFFICIENT_DATA" and nd["reasons"] == []
    short = P.pair_filters(d1(5), r)["checks"]; assert short["median_quote_vol"] == "INSUFFICIENT_DATA"


def test_replay_shadow_equals_off_and_enforce_subset(tmp_path):
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir(); (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    off = replay.run(["TST-USD"], R(protections_mode="off"), str(d))
    sh = replay.run(["TST-USD"], R(protections_mode="shadow"), str(d))
    en = replay.run(["TST-USD"], R(protections_mode="enforce"), str(d))
    assert [t["net_r"] for t in off["trades"]] == [t["net_r"] for t in sh["trades"]]
    assert {t["entry_ts"] for t in en["trades"]} <= {t["entry_ts"] for t in off["trades"]}


def test_lookahead_analysis_passes(tmp_path):
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir(); (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    rep = analysis.lookahead(["TST-USD"], R(protections_mode="enforce", panel_mode="enforce"), str(d), cuts=(0.97, 0.99))
    assert rep["ok"] and all(c["events_before_cut"] > 0 for c in rep["cuts"])


def test_lookahead_detector_catches_peeking(tmp_path, monkeypatch):
    """Sanidade do detector: um replay que espreita o futuro tem de falhar."""
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir(); (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    real = replay.run
    def peeking(symbols, rules, data_dir="data", **kw):
        res = real(symbols, rules, data_dir, **kw)
        last = replay.load_cached(symbols[0], data_dir)[-1]["close"]
        res["events"] = [{**e, "peek": last} for e in res["events"]]
        return res
    monkeypatch.setattr(replay, "run", peeking)
    rep = analysis.lookahead(["TST-USD"], R(), str(d), cuts=(0.97,))
    assert rep["cuts"][0]["events_before_cut"] > 0 and not rep["ok"]


def _h1(n, seed=1):
    import random; rnd = random.Random(seed); px = 100.0; out = []
    for i in range(n):
        o = px; px *= math.exp(rnd.gauss(0, 0.012)); hi, lo = max(o, px) * (1 + abs(rnd.gauss(0, .004))), min(o, px) * (1 - abs(rnd.gauss(0, .004)))
        out.append({"start": i * H, "open": o, "high": hi, "low": lo, "close": px, "volume": 1.0})
    return out


@pytest.mark.parametrize("fn", [community.bbandrsi, community.adxmomentum])
def test_community_causal_and_hard_stop(fn):
    r = load_rules(); h1 = _h1(3000)
    full = fn(h1, r); part = fn(h1[:2000], r)
    cut = h1[1999]["start"]
    assert [t for t in full if t["exit_ts"] < cut - H] == [t for t in part if t["exit_ts"] < cut - H]
    assert full and all(t["net_r"] >= -1.6 or t["why"] == "STOP_GAP" for t in full)   # stop −8% ≈ −1R (+custos)


def test_rsi_bounds():
    v = [x for x in community.rsi_wilder([x["close"] for x in _h1(300)]) if x is not None]
    assert v and all(0 <= x <= 100 for x in v)


def test_live_pipeline_records_protections(desk_state):
    rules = load_rules(); cli = FakeClient(path_hours())
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    plans = store.read("trade_plan.csv"); assert len(plans) == 1   # shadow: não bloqueia
    pr = json.loads(plans[0]["prot"]); assert pr["mode"] == "shadow" and "checks" in pr
    ob = [a for a in store.outbox() if a["type"] == "ENTRY_ALERT"]
    assert "Protections (shadow)" in ob[0]["text"] and ob[0]["data"]["protections"]["mode"] == "shadow"


def test_live_enforce_vetoes_on_low_volume(desk_state):
    rules = R(protections_mode="enforce", filt_min_quote_vol=1e12); cli = FakeClient(path_hours())
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    assert store.read("trade_plan.csv") == []
    assert any("PROT_VETO" in x["reason"] and "VOLUME_FILTER" in x["reason"] for x in store.read("plan_rejections.csv"))
