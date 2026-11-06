import math, numpy as np
from desk.research import exitgrid as G


def bars(prices):
    p = np.array(prices, float); o = p.copy(); c = p.copy(); return o, p * 1.001, p * 0.999, c


def test_grid_size_and_unique():
    g = G.exit_grid(); assert len(g) == 720 and len({e["id"] for e in g}) == 720


def test_tp_hit_net_of_costs():
    o, h, l, c = bars([100, 100, 101, 102, 103, 104])
    a = np.full(6, 1.0)
    r, j, s0, code = G.sim_exit(o, h, l, c, a, 1, 100.0, 98.0, 6, 2, 0.02, 1.0, 0, 0.0, 0, 0)
    assert code == 2 and abs(s0 - 98.0) < 1e-9
    fi, fo = 100 * (1 + G.SLIP), 102 * (1 - G.SLIP)
    assert abs(r - (fo - fi - (fi + fo) * G.TAKER) / 2.0) < 1e-9


def test_stop_first_when_both_hit_and_hard_cap():
    o = np.array([100, 100.0]); h = np.array([100, 120.0]); l = np.array([100, 80.0]); c = np.array([100, 100.0])
    r, j, s0, code = G.sim_exit(o, h, l, c, np.ones(2), 1, 100.0, 50.0, 2, 0, 0.0, 1.0, 0, 0.0, 0, 0)
    assert code == 1 and abs(s0 - 92.0) < 1e-9 and r < -1        # wick 50 capado a −8%; stop conservador


def test_no_lookahead_end_truncation():
    rng = np.random.default_rng(1); p = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    o, h, l, c = bars(p); a = np.full(400, 0.5)
    full = G.sim_exit(o, h, l, c, a, 10, o[10], o[10] * 0.97, 400, 1, 2.0, 0.0, 1, 3.0, 1, 0)
    cut = G.sim_exit(o[:200], h[:200], l[:200], c[:200], a[:200], 10, o[10], o[10] * 0.97, 200, 1, 2.0, 0.0, 1, 3.0, 1, 0)
    if full[1] < 199: assert full[:3] == cut[:3]


def test_portfolio_max_positions_and_cap():
    n = 7; ent = np.arange(n, dtype=np.int64); ex = np.full(n, 100, np.int64)
    tk, pnl = G.portfolio(ent, ex, np.ones(n), np.full(n, 0.01), np.ones(n, bool), 10000.0, 0.01, 0.15, 5)
    assert tk.sum() == 5 and abs(pnl[0] - 15.0) < 1e-9          # teto 15% × 1% de distância = 0.15% de risco


def test_prereg_frozen_hash():
    import json, hashlib, os
    if not os.path.exists(G.PREREG): return
    d = json.load(open(G.PREREG)); h = d.pop("sha256")
    assert hashlib.sha256(json.dumps(d, sort_keys=True, default=float).encode()).hexdigest() == h
    assert d["n_variants"] == 720 * len(d["filters"])
