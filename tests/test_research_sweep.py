import numpy as np, pytest
from desk.research import sweep as S

H = S.H


def synth(n=3000, seed=0, drift=0.0):
    rng = np.random.default_rng(seed); c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = np.r_[c[0], c[:-1]]; hi = np.maximum(o, c) * 1.002; lo = np.minimum(o, c) * 0.998
    return {"start": np.arange(n, dtype=np.float64) * H + S.DEV0, "open": o, "high": hi, "low": lo, "close": c, "volume": np.ones(n)}


def test_grid_is_preregistered_42():
    assert len(S.configs()) == 42 and len({c["id"] for c in S.configs()}) == 42


def test_resample_4h():
    d = synth(16); r = S.resample(d, 4)
    assert len(r["open"]) == 4 and r["open"][1] == d["open"][4] and r["close"][1] == d["close"][7]
    assert r["high"][0] == d["high"][:4].max() and r["low"][0] == d["low"][:4].min()


def test_no_lookahead_truncation():
    d = synth(); cfg = next(c for c in S.configs() if c["id"] == "sma_20_100_1h")
    t1 = S.DEV0 + 3000 * H; cut = S.DEV0 + 2000 * H
    full, _ = S.simulate(d, S.signal(d, cfg), S.DEV0, t1)
    dd = {k: v[:2000] for k, v in d.items()}
    part, _ = S.simulate(dd, S.signal(dd, cfg), S.DEV0, t1)
    done = lambda tr: [t for t in tr if t["why"] != "END" and t["exit_ts"] < cut - H]
    assert done(full) == done(part) and done(full)


def test_stop_minus_8_with_costs_and_no_reentry_until_signal_off():
    n = 50; o = np.full(n, 100.0); c = o.copy(); hi = o * 1.001; lo = o * 0.999
    lo[10] = 90.0                                  # toca o stop 92
    d = {"start": np.arange(n) * H + S.DEV0, "open": o, "high": hi, "low": lo, "close": c, "volume": np.ones(n)}
    want = np.ones(n, dtype=np.int8); want[30] = 0
    tr, r = S.simulate(d, want, S.DEV0, S.DEV0 + n * H)
    assert tr[0]["why"] == "STOP" and tr[0]["r"] == pytest.approx((92 * (1 - S.SIDE_COST) / (100 * (1 + S.SIDE_COST)) - 1) / 0.08)
    assert tr[1]["entry_ts"] == d["start"][32]       # só reentra depois do sinal desligar (want[30]=0 → entra em 32)
    assert np.prod(1 + r[:12]) - 1 == pytest.approx((1 - S.SIDE_COST) * (0.92 - S.SIDE_COST) - 1, abs=1e-9)   # custo aditivo na barra


def test_dsr_penalises_more_trials_and_rc_on_noise():
    rng = np.random.default_rng(1); M = rng.normal(0, 0.01, (40, 700))
    best = M[np.argmax(M.mean(axis=1))]; srs = M.mean(axis=1) / M.std(axis=1, ddof=1)
    d40 = S.deflated_sharpe(best, srs)["dsr"]; d5 = S.deflated_sharpe(best, srs[:5])["dsr"]
    assert d40 < 0.95 and d5 >= d40 - 1e-9
    assert S.reality_check(M, B=300)["p"] > 0.05
    M2 = M.copy(); M2[0] += 0.004                       # um edge real e grande
    assert S.reality_check(M2, B=300)["p"] < 0.05


def test_walk_forward_uses_only_past():
    days = np.arange(800); a = np.r_[np.full(500, 0.002), np.full(300, -0.002)] + np.random.default_rng(2).normal(0, 0.001, 800)
    b = -a
    wf = S.walk_forward({"a": a, "b": b}, days)
    assert wf["folds"] == 4 and wf["picks"][0] == "a"
