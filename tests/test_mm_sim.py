import math, random
from desk import mm_sim, revx_tape
from desk.rules import load_rules

D = 86_400_000


def tape(days=2, seed=1, drift=0.0, every_s=10):
    rnd = random.Random(seed); px = 100.0; out = []
    for k in range(days * 86400 // every_s):
        px *= math.exp(rnd.gauss(drift, 0.0005))
        side = "buy" if rnd.random() < 0.5 else "sell"
        out.append({"ts": k * every_s * 1000, "px": px * (1.0003 if side == "buy" else 0.9997), "qty": rnd.uniform(0.05, 0.5), "side": side})
    return out


def test_mid_no_lookahead():
    t = [{"ts": i * 1000, "px": float(i), "qty": 1, "side": "buy"} for i in range(100)]
    times = [x["ts"] for x in t]; prices = [x["px"] for x in t]
    assert mm_sim.mid_at(prices, times, 50_000) == mm_sim.mid_at(prices, times, 50_000)  # determinístico
    assert mm_sim.mid_at(prices, times, 50_000) < 50  # só trades estritamente antes de t


def test_long_only_and_order_cap():
    r = load_rules(); tp = tape()
    res = mm_sim.simulate(tp, 0, 2 * D, r, kappa=5000)
    assert res["orders_per_day_max"] <= 1000
    sold = sum(x["qty"] for x in res["round_trips"]); assert res["buys"] >= 0
    # nunca mais vendido do que comprado: round trips só fecham lotes comprados
    assert all(x["qty"] > 0 and x["buy"] > 0 for x in res["round_trips"])
    assert res["inv_max"] <= r.mm_max_inv_frac + r.mm_order_usd / r.mm_capital_usd + 1e-9


def _flat(n, px=100.0, side="buy", step=10):
    return [{"ts": i * step * 1000, "px": px, "qty": 1.0, "side": side} for i in range(n)]


def test_touch_does_not_fill_and_through_fills_half():
    r = load_rules()
    base = _flat(400)  # 4000 s de histórico a 100 (σ=0)
    t_q = 3900_000
    # a 1ª cotação útil está em t múltiplo de 300 s ≥ warm-up; injecta trades de venda no bid exacto e através
    h = max(r.mm_min_half_bps / 1e4, 1 / 5000)
    bid = 100 * (1 - h)
    touch = [{"ts": 3600_000 + 5000, "px": bid, "qty": 1.0, "side": "sell"}]
    res = mm_sim.simulate(sorted(base + touch, key=lambda x: x["ts"]), 3600_000, 3900_000, r, kappa=5000)
    assert res["buys"] == 0
    through = [{"ts": 3600_000 + 5000, "px": bid * 0.999, "qty": 0.01, "side": "sell"}]
    res = mm_sim.simulate(sorted(base + through, key=lambda x: x["ts"]), 3600_000, 3900_000, r, kappa=5000)
    assert res["buys"] == 1


def test_latency_blocks_instant_fill():
    r = load_rules(); base = _flat(400); h = max(r.mm_min_half_bps / 1e4, 1 / 5000)
    early = [{"ts": 3600_000 + 1000, "px": 100 * (1 - h) * 0.99, "qty": 1.0, "side": "sell"}]
    res = mm_sim.simulate(sorted(base + early, key=lambda x: x["ts"]), 3600_000, 3900_000, r, kappa=5000)
    assert res["buys"] == 0


def test_queue_share_and_wrong_side():
    r = load_rules(); base = _flat(400); h = max(r.mm_min_half_bps / 1e4, 1 / 5000)
    buy_aggr = [{"ts": 3600_000 + 5000, "px": 100 * (1 - h) * 0.99, "qty": 1.0, "side": "buy"}]
    res = mm_sim.simulate(sorted(base + buy_aggr, key=lambda x: x["ts"]), 3600_000, 3900_000, r, kappa=5000)
    assert res["buys"] == 0  # agressor comprador não enche o nosso bid


def test_hard_stop_and_end_liquidation_pay_taker():
    r = load_rules(); base = _flat(400); h = max(r.mm_min_half_bps / 1e4, 1 / 5000)
    fill = [{"ts": 3600_000 + 5000, "px": 100 * (1 - h) * 0.999, "qty": 10.0, "side": "sell"}]
    crash = [{"ts": 3600_000 + 60_000 + i * 1000, "px": 85.0, "qty": 1.0, "side": "sell"} for i in range(5)]
    res = mm_sim.simulate(sorted(base + fill + crash, key=lambda x: x["ts"]), 3600_000, 3900_000, r, kappa=5000)
    assert res["hard_stops"] == 1
    rt = res["round_trips"]; assert rt and rt[0]["why"] == "HARD_STOP" and rt[0]["pnl"] < 0
    assert rt[0]["sell"] < 85.0  # slippage aplicada


def test_score_and_verdict_frozen():
    r = load_rules()
    s = mm_sim.score_rts([{"pnl": 0.01, "notional": 20, "bps": 5}] * 50, 0.08)
    assert abs(s["expectancy_r"] - 0.01 / 1.6) < 1e-9
    fake = {"X": {"MM_AS": {"full": {"rt": {**s}, "max_dd": 0.01}, "oos": {"rt": s}},
                  "MM_WIDE": {"full": {"rt": {**s}, "max_dd": 0.01}, "oos": {"rt": s}}}, "Y": {"status": "INSUFFICIENT_DATA"}}
    v = mm_sim.verdict(fake, r)
    assert v["X:MM_AS"] == "TRADE_OFF" and v["Y"] == "INSUFFICIENT_DATA"   # +5 bps/rt ≈ 0.006R ≪ 0.4R
    assert r.threshold_expectancy_r == 0.4 and r.threshold_trades == 40


def test_run_insufficient_and_kappa(tmp_path):
    import json
    tp = tape(days=3)
    for d in range(3):
        with open(tmp_path / f"AAA-USD_{d * D}.jsonl", "w") as f:
            for x in tp:
                if d * D <= x["ts"] < (d + 1) * D: f.write(json.dumps(x) + "\n")
    r = load_rules(); res = mm_sim.run(["AAA-USD", "BBB-USD"], str(tmp_path), r)
    assert res["BBB-USD"]["status"] == "INSUFFICIENT_DATA"
    a = res["AAA-USD"]; assert a["kappa"] > 0 and "MM_AS" in a and a["cut"] > a["t0"]


def test_book_stats():
    ob = {"data": {"bids": [{"price": "99.99", "quantity": "1"}, {"price": "99.0", "quantity": "5"}],
                   "asks": [{"price": "100.01", "quantity": "2"}]}}
    s = revx_tape.book_stats(ob); assert abs(s["spread_bps"] - 2.0) < 1e-6 and s["depth10_bid"] > 99 and s["depth10_bid"] < 100.5


def test_touch_flag_only_in_optimistic_mode():
    r = load_rules(); base = _flat(400); h = max(r.mm_min_half_bps / 1e4, 1 / 5000); bid = 100 * (1 - h)
    touch = [{"ts": 3600_000 + 5000, "px": bid, "qty": 1.0, "side": "sell"}]
    tp = sorted(base + touch, key=lambda x: x["ts"])
    assert mm_sim.simulate(tp, 3600_000, 3900_000, r, 5000)["buys"] == 0
    assert mm_sim.simulate(tp, 3600_000, 3900_000, r, 5000, touch=True)["buys"] == 1
