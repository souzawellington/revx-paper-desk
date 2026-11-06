"""Painel de analistas (repo virattt/ai-hedge-fund adaptado): só veta/reduz, nunca aumenta."""
import json, math
import pytest
from desk.rules import load_rules, Rules
from desk import panel as P, store, run as desk_run, replay
from tests.test_desk import path_hours, FakeClient, T0, H, D, desk_state
from bot.variants import resample


def series(n, step, start=100.0, vol=0.0, period=1):
    out, px = [], start
    for i in range(n):
        o = px; px = px * (1 + step) + (vol * px if (i // period) % 2 else -vol * px)
        out.append({"start": i * D, "open": o, "high": max(o, px) * 1.01, "low": min(o, px) * 0.99, "close": px, "volume": 1.0 + i * 0.01})
    return out


def rules_with(**kw):
    r = load_rules(); return Rules({**r.p, **kw})


def test_uptrend_bullish_downtrend_bearish():
    r = rules_with(panel_mode="enforce")
    up, dn = series(150, 0.01), series(150, -0.01)
    du = P.evaluate(r, up, up, up); dd = P.evaluate(r, dn, dn, dn)
    assert {v["analyst"]: v["signal"] for v in du["votes"]}["trend_4h"] == P.BULL
    assert du["action"] in ("KEEP", "REDUCE") and dd["action"] == "VETO" and dd["size_mult"] == 0


def test_insufficient_data_no_effect():
    r = rules_with(panel_mode="enforce")
    d = P.evaluate(r, series(10, 0.01), series(10, 0.01), None)
    assert d["action"] == "NO_OPINION" and d["size_mult"] == 1.0
    assert all(v["signal"] == P.ABST for v in d["votes"])


@pytest.mark.parametrize("step", [0.02, 0.0, -0.02, 0.005])
def test_never_enlarges(step):
    r = rules_with(panel_mode="enforce", panel_neutral_mult=7.0)    # mesmo com parâmetro abusivo
    s = series(150, step, vol=0.03, period=3)
    d = P.evaluate(r, s, s, s, [s, s])
    assert 0 <= d["size_mult"] <= 1 and d["notional_cap_frac"] <= r.max_position_frac
    q, _ = P.apply(10.0, 100.0, 10_000, d, r)
    assert q <= 10.0


def test_correlation_and_vol_cap_only_reduce():
    s = series(120, 0.003, vol=0.02, period=2)
    m, avg = P.correlation_mult(s, [s]); assert avg == pytest.approx(1.0, abs=1e-6) and m == 0.70
    assert P.correlation_mult(s, [])[0] == 1.0
    for v in (0.05, 0.2, 0.4, 1.5, None):
        assert P.vol_cap_frac(v, 0.15) <= 0.15


def test_llm_hook_clamped_and_off_by_default():
    assert load_rules().panel_llm_hook is False and load_rules().panel_mode == "shadow"
    assert P.clamp_llm(0.5, 2.0) == 0.5 and P.clamp_llm(0.5, 0.2) == 0.2 and P.clamp_llm(0.5, "x") == 0.5
    s = series(150, 0.01); r = rules_with(panel_mode="enforce")
    assert P.evaluate(r, s, s, s, llm=5.0)["size_mult"] <= 1.0
    assert P.evaluate(r, s, s, s, llm=0.0)["size_mult"] == P.evaluate(r, s, s, s)["size_mult"]   # hook off -> ignorado


def test_shadow_mode_no_effect():
    s = series(150, -0.01); r = rules_with(panel_mode="shadow")
    d = P.evaluate(r, s, s, s); assert d["action"] == "VETO"
    assert P.apply(3.0, 100, 10_000, d, r)[0] == 3.0


def test_pipeline_records_panel_votes_in_outbox(desk_state):
    rules = load_rules(); cli = FakeClient(path_hours())
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    plans = store.read("trade_plan.csv"); assert len(plans) == 1 and plans[0]["panel"]
    ob = [a for a in store.outbox() if a["type"] == "ENTRY_ALERT"]
    pd_ = ob[0]["data"]["panel"]
    assert len(pd_["votes"]) == 5 and {v["analyst"] for v in pd_["votes"]} == set(P.ANALYSTS)
    assert "Painel (shadow)" in ob[0]["text"]


def test_store_migrates_old_header(desk_state):
    old = store.SCHEMAS["trade_plan.csv"][:-1]
    with open(store.path("trade_plan.csv"), "w") as f: f.write(",".join(old) + "\n" + ",".join(["x"] * len(old)) + "\n")
    store.append("trade_plan.csv", [{"plan_id": "y", "panel": "{}"}])
    rows = store.read("trade_plan.csv"); assert [r["plan_id"] for r in rows] == ["x", "y"] and rows[1]["panel"] == "{}"


def test_replay_shadow_equals_off_and_enforce_never_more_trades(tmp_path):
    h1 = path_hours(); d = tmp_path / "data"; d.mkdir()
    (d / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    off = replay.run(["TST-USD"], rules_with(panel_mode="off"), str(d))
    sh = replay.run(["TST-USD"], rules_with(panel_mode="shadow"), str(d))
    en = replay.run(["TST-USD"], rules_with(panel_mode="enforce"), str(d))
    assert [t["net_r"] for t in off["trades"]] == [t["net_r"] for t in sh["trades"]]
    assert len(en["trades"]) <= len(off["trades"])
    for a, b in zip(en["trades"], off["trades"]):
        if a["entry_ts"] == b["entry_ts"]: assert a["qty"] <= b["qty"] + 1e-9


def test_panel_never_imports_write_endpoints():
    src = open("desk/panel.py").read()
    for bad in ("place_order", "create_order", "requests.post", "cancel_order", "anthropic", "openai"):
        assert bad not in src
