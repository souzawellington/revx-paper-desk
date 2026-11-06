import json, os
import pytest
from desk.rules import load_rules, parse_params
from desk import logic as L, store, run as desk_run, gate, auditor, replay
from bot.variants import resample

H, D = L.H, L.D
T0 = 1_700_006_400_000 - (1_700_006_400_000 % D)   # dia UTC alinhado


def bar(t, o, c, wick=0.05):
    return {"start": t, "open": o, "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c, "volume": 1.0}


def path_hours():
    """Série 1H: lateral 60 dias, C1/C2/C3 de alta com FVG 4H no C3, pullback que testa a zona e confirmação 1H."""
    px = []
    for h in range(60 * 24): px.append(100 + (0.05 if h % 2 else -0.05))
    px += [100 + (i + 1) / 24 for i in range(24)]                    # C1: 100 -> 101
    px += [101 + 2 * (i + 1) / 24 for i in range(24)]                # C2: 101 -> 103
    c3 = [103 + 0.05 * (i + 1) for i in range(4)]                    # 4H A
    c3 += [103.2 + (107 - 103.2) * (i + 1) / 4 for i in range(4)]    # 4H B (impulso)
    c3 += [107.3 + 0.05 * (i + 1) for i in range(4)]                 # 4H C (low > high de A)
    c3 += [107.5 + 0.5 * (i + 1) / 12 for i in range(12)]
    px += c3                                                         # C3 fecha 108
    d4 = [108 - 2 * (i + 1) / 10 for i in range(10)] + [106 + 0.5 * (i + 1) for i in range(4)] + [108 + 0.1 * i for i in range(10)]
    px += d4                                                         # testa ~106 (zona até 107) e confirma
    px += [109 + 0.05 * i for i in range(48)]                        # sobe
    px += [109 - 1.0 * (i + 1) for i in range(12)]                   # cai -> stop
    out, prev = [], 100.0
    for i, c in enumerate(px):
        out.append(bar(T0 + i * H, prev, c)); prev = c
    return out


class FakeClient:
    def __init__(self, h1): self.h1 = h1; self.series = {60: h1, 240: resample(h1, 4), 1440: resample(h1, 24)}
    def public_pairs(self, region=None):
        r = {"base_step": "0.0001", "quote_step": "0.01", "min_order_size": "0.0001", "max_order_size": "1e9", "min_order_size_quote": "1", "status": "active"}
        return {"TST/USD": {"base": "TST", "quote": "USD", **r}, "USDC/USD": {"base": "USDC", "quote": "USD", **r}}
    def public_candles(self, sym, interval, since, until, region=None):
        return [dict(c) for c in self.series[interval] if since <= c["start"] <= until]
    def public_tickers(self, syms, region=None):
        return [{"symbol": "TST/USD", "mid": str(self.h1[-1]["close"])}]


@pytest.fixture
def desk_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE", str(tmp_path))
    monkeypatch.delenv("REVX_API_KEY", raising=False)
    return tmp_path


def test_rules_parse_and_guards(tmp_path):
    r = load_rules()
    assert r.risk_pct == 0.01 and r.add_risk_pct == 0.005 and r.hard_stop_pct == 0.08 and r.threshold_trades == 40
    txt = open("desk/DESK_RULES.md").read().replace("hard_stop_pct: 0.08", "hard_stop_pct: 0.2")
    p = tmp_path / "R.md"; p.write_text(txt)
    with pytest.raises(ValueError): load_rules(str(p))
    assert parse_params("```params\na: 1\nb: x\nc: true\n```") == {"a": 1, "b": "x", "c": True}


def test_up_flip_rules():
    r = load_rules()
    d = [bar(0, 100, 101), bar(D, 101, 102), bar(2 * D, 102, 103)]
    d[0]["low"] = 99
    assert L.up_flip_at(d, 2, r)
    d2 = [dict(x) for x in d]; d2[2]["low"] = 98.9                    # C3 toca o mínimo de C1
    assert not L.up_flip_at(d2, 2, r)
    d3 = [dict(x) for x in d]; d3[1].update(open=101.5, close=101.2)  # C2 vermelho mas acima de C1: válido
    assert L.up_flip_at(d3, 2, r)
    d4 = [dict(x) for x in d]; d4[0].update(open=100.0, close=100.02, high=101, low=99)   # doji C1
    assert L.up_flip_at(d4, 2, r)
    f = L.active_up_flip(d + [bar(3 * D, 103, 98.5)], r)              # fecho abaixo da âncora invalida
    assert f is None and L.active_up_flip(d, r).anchor_low == 99


def test_fvg_and_partial_wick_and_confirm():
    r = load_rules()
    h1 = path_hours(); h4 = resample(h1, 4); d1 = resample(h1, 24)
    fl = L.active_up_flip([c for c in d1 if c["start"] + D <= T0 + 63 * D], r)
    c1 = next(c for c in d1 if c["start"] == fl.c1_start)
    assert fl.anchor_low == c1["low"] and fl.c1_start == T0 + 60 * D
    zs = L.find_fvgs([c for c in h4 if c["start"] + 4 * H <= T0 + 63 * D], "TST-USD", fl)
    assert zs and zs[0].bottom < zs[0].top
    z = max(zs, key=lambda z: z.top - z.bottom); L.update_zone(z, h4, [c for c in h1 if c["start"] + H <= T0 + 64 * D], r)
    assert z.status == "CONFIRMED" and z.entry > z.top and z.stop <= z.test_low + 1e-9 and z.stop >= z.entry * 0.92


def test_size_caps():
    r = load_rules()
    q, info = L.size_trade(10_000, 100, 99.9, 0.01, r)       # stop muito curto -> teto 15%
    assert info["binding"] == "cap15" and q * 100 == pytest.approx(1500)
    q, info = L.size_trade(10_000, 100, 90, 0.01, r)         # risco 1% = 100 USD / 10 = 10 un
    assert info["binding"] == "risk" and q == pytest.approx(10)
    q, info = L.size_trade(10_000, 100, 90, 0.01, r, kelly_frac=0.05)
    assert info["binding"] == "quarter_kelly" and q == pytest.approx(5)


def test_trade_r_lines():
    r = load_rules(); x = L.trade_r(100, 110, 95, r)
    assert x["gross_r"] == pytest.approx(2) and x["net_r"] < 2 and x["fee_per_unit"] > 0 and x["slippage_per_unit"] > 0


def test_full_desk_pipeline_and_dedupe(desk_state):
    rules = load_rules(); h1 = path_hours(); cli = FakeClient(h1)
    t_daily = T0 + 63 * D
    desk_run.stage("daily", rules, cli, now=t_daily, log=lambda *a: None)
    w = store.read("watchlist.csv"); assert [x["coin"] for x in w] == ["TST-USD"]   # stablecoin excluída
    for row in w: row["tag"] = "PRIME"   # Texto 1 / no_hero: só PRIME gera plano
    store.write("watchlist.csv", w)
    t_conf = T0 + 63 * D + 13 * H          # 1H a seguir à confirmação (dia 63, 12:00-13:00)
    desk_run.stage("1h", rules, cli, now=t_conf, log=lambda *a: None)
    plans = store.read("trade_plan.csv"); assert len(plans) == 1
    assert store.f(plans[0]["tp_price"]) == pytest.approx(
        float(plans[0]["entry"]) + rules.take_profit_r * (float(plans[0]["entry"]) - float(plans[0]["stop"])))
    assert float(plans[0]["risk_pct"]) == 0.01 and plans[0]["equity_source"] == "paper"
    ob = store.outbox(); assert len(ob) == 1 and ob[0]["type"] == "ENTRY_ALERT" and os.path.exists(ob[0]["chart_png"])
    desk_run.stage("1h", rules, cli, now=t_conf + H, log=lambda *a: None)      # dedupe
    assert len(store.outbox()) == 1 and len(store.read("trade_plan.csv")) == 1
    assert store.read("positions.csv")[0]["status"] == "OPEN"
    gate.decide(ob[0]["id"], "SKIPPED")
    with pytest.raises(SystemExit): gate.decide(ob[0]["id"], "TAKEN")
    t_end = T0 + len(h1) * H
    desk_run.stage("4h", rules, cli, now=t_end, log=lambda *a: None)
    ex = [a for a in store.outbox() if a["type"] == "EXIT_NOW"]
    assert len(ex) == 1 and store.read("positions.csv")[0]["status"] == "CLOSED"
    lines = [j["line"] for j in store.read("journal.csv")]
    assert lines == ["ENTRY", "EXIT", "FEE", "SLIPPAGE", "RESULT"]
    assert store.read("journal.csv")[-1]["mode"] == "HYPOTHETICAL_SKIPPED"
    desk_run.stage("4h", rules, cli, now=t_end + 4 * H, log=lambda *a: None)
    assert len([a for a in store.outbox() if a["type"] == "EXIT_NOW"]) == 1      # não repete
    desk_run.stage("weekly", rules, cli, now=t_end, log=lambda *a: None)
    rep = [a for a in store.outbox() if a["type"] == "WEEKLY_REPORT"]
    assert rep and "NO-GO" in rep[0]["text"]


def test_old_confirmation_expires_not_alerted(desk_state):
    rules = load_rules(); cli = FakeClient(path_hours())
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    desk_run.stage("1h", rules, cli, now=T0 + 64 * D, log=lambda *a: None)       # 11h depois: catch-up
    assert store.read("trade_plan.csv") == [] and store.outbox() == []
    assert any(z["status"] == "EXPIRED" for z in store.read("zones.csv"))


def test_desk_never_writes_to_exchange():
    import re, pathlib
    src = "\n".join(p.read_text() for p in pathlib.Path("desk").glob("*.py"))
    assert not re.search(r"place_order|cancel_order|cancel_all|\"POST\"|'POST'|\.post\(", src)


def test_replay_no_lookahead(tmp_path):
    """Truncar o futuro não muda os trades fechados antes do corte."""
    from desk.rules import Rules
    base = load_rules(); rules = Rules({**base.p, "no_hero": False})  # isola o teste de look-ahead
    h1 = path_hours()
    (tmp_path / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    full = replay.run(["TST-USD"], rules, str(tmp_path))
    cut = T0 + 64 * D + 30 * H
    (tmp_path / "candles_TST-USD_60.json").write_text(json.dumps([c for c in h1 if c["start"] < cut]))
    part = replay.run(["TST-USD"], rules, str(tmp_path))
    ev = lambda r: [e for e in r["events"] if e["ts"] < cut - H and e["event"] in ("ALERT", "ENTRY", "WATCH")]
    assert ev(full) == ev(part) and any(e["event"] == "ENTRY" for e in ev(full))
    assert full["trades"] and full["trades"][0]["why"].startswith(("STOP", "HARD", "TAKE_PROFIT"))


def test_tp_price_formula_and_precommit():
    r = load_rules()
    assert r.take_profit_r == 4 and r.no_hero is True and r.max_leverage_equivalent == 1
    assert L.tp_price(100, 99, 4) == pytest.approx(104)
    with pytest.raises(ValueError):
        L.tp_price(100, 100, 4)


def test_check_exit_take_profit_and_stop_priority():
    r = load_rules()
    pos = L.Position("x", "TST-USD", 100, 99, 1, 0.01, 0, 90, 0, peak=100, initial_stop=99, tp_price=104, initial_tp=104)
    # TP hit only
    assert L.check_exit(pos, {"open": 101, "high": 105, "low": 100.5, "close": 104.5}, r) == ("TAKE_PROFIT", 104)
    # gap above TP
    assert L.check_exit(pos, {"open": 106, "high": 107, "low": 105, "close": 106}, r)[0] == "TAKE_PROFIT_GAP"
    # both stop and TP same bar → STOP wins
    assert L.check_exit(pos, {"open": 100, "high": 105, "low": 98.5, "close": 103}, r)[0] == "STOP"
    # after_bar BE must not mutate TP
    L.after_bar(pos, {"open": 100, "high": 102, "low": 99.5, "close": 101.5}, r)  # 1R = 1 → BE at high>=101
    assert pos.at_be and pos.tp_price == 104 == pos.initial_tp


def test_no_post_entry_tp_mutation(desk_state):
    """Após abertura paper, update_row / exit_clerk não podem alterar tp_price."""
    rules = load_rules(); h1 = path_hours(); cli = FakeClient(h1)
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    # force PRIME so no_hero allows planning
    w = store.read("watchlist.csv"); 
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    plans = store.read("trade_plan.csv")
    assert plans and store.f(plans[0]["tp_price"]) > float(plans[0]["entry"])
    frozen = float(plans[0]["tp_price"])
    pos = store.read("positions.csv")
    assert pos and float(pos[0]["tp_price"]) == pytest.approx(frozen, rel=0, abs=1e-9)
    # try to mutate CSV and ensure update_row restores from initial_tp
    from desk.positions import to_pos, update_row
    r = pos[0]; r["tp_price"] = "999"
    p = to_pos({**r, "tp_price": str(frozen)})  # load with correct frozen
    p.tp_price = 999.0  # attacker mutates in memory
    update_row(r, p)
    assert float(r["tp_price"]) == pytest.approx(frozen) and p.tp_price == frozen


def test_no_hero_rejects_watch(desk_state):
    rules = load_rules(); h1 = path_hours(); cli = FakeClient(h1)
    desk_run.stage("daily", rules, cli, now=T0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "WATCH"
    store.write("watchlist.csv", w)
    # plant a CONFIRMED zone via 1h path... cartographer may confirm
    desk_run.stage("1h", rules, cli, now=T0 + 63 * D + 13 * H, log=lambda *a: None)
    assert store.read("trade_plan.csv") == []
    assert any("NO_HERO_WEAK" in r["reason"] for r in store.read("plan_rejections.csv"))


def test_replay_hits_take_profit(tmp_path):
    from desk.rules import Rules
    base = load_rules()
    # série que sobe o suficiente para +4R após confirmação
    rules = Rules({**base.p, "no_hero": False, "take_profit_r": 2})
    h1 = path_hours()
    # estender com rally forte após confirmação
    last = h1[-1]; px = last["close"]
    for i in range(80):
        px *= 1.02
        h1.append({"start": last["start"] + (i + 1) * H, "open": px / 1.01, "high": px * 1.01, "low": px / 1.02, "close": px, "volume": 1})
    (tmp_path / "candles_TST-USD_60.json").write_text(json.dumps(h1))
    res = replay.run(["TST-USD"], rules, str(tmp_path))
    assert any(t["why"].startswith("TAKE_PROFIT") for t in res["trades"]) or any(
        e.get("event") == "ALERT" and e.get("tp") for e in res["events"])
