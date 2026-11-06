"""Testes do estudo de scalping (desk/research/scalp.py). Dados sintéticos, sem rede."""
import hashlib, json, math
import numpy as np
import pytest
from desk.research import scalp as S

T0 = S.DEV0


def grid(o, h, l, c, v=None):
    n = len(c); return {"ts": T0 + np.arange(n, dtype=np.int64) * S.M1, "o": np.array(o, float), "h": np.array(h, float),
                        "l": np.array(l, float), "c": np.array(c, float), "v": np.ones(n) if v is None else np.array(v, float), "bad": np.zeros(n, bool)}


def sim(g, sig, sld, tpd=None, maker=False, tstop=50, inval=None, dyn=None, slip=0.0, fee=0.0, block=None):
    n = len(g["c"]); s = np.zeros(n, bool); s[sig] = True
    return S.simulate(g["o"], g["h"], g["l"], g["c"], s, g["c"], np.full(n, float(sld)), np.full(n, np.nan if tpd is None else float(tpd)),
                      np.full(n, np.nan) if dyn is None else np.asarray(dyn, float), dyn is not None,
                      np.zeros(n, bool) if inval is None else np.asarray(inval, bool), tstop, maker, slip, fee, 0.0, 3,
                      np.zeros(n, bool) if block is None else block, 0, n, n + 2)


def test_taker_enters_next_open_and_hits_target():
    g = grid(o=[100, 101, 101, 101], h=[100, 101, 103, 101], l=[100, 101, 101, 101], c=[100, 101, 102, 101])
    ei, xi, ep, xp, sp, R, ret, why, nsig, nmiss = sim(g, [0], sld=1.0, tpd=1.5)
    assert ei[0] == 1 and ep[0] == 101 and why[0] == 0 and math.isclose(xp[0], 102.5) and math.isclose(R[0], 1.5)


def test_stop_wins_when_stop_and_target_same_bar():
    g = grid(o=[100, 100, 100], h=[100, 100, 105], l=[100, 100, 95], c=[100, 100, 100])
    *_, R, ret, why, nsig, nmiss = sim(g, [0], sld=1.0, tpd=1.0)
    assert why[0] == 1 and math.isclose(R[0], -1.0)


def test_gap_below_stop_fills_at_open():
    g = grid(o=[100, 100, 97], h=[100, 100, 97], l=[100, 100, 96], c=[100, 100, 97])
    *_, R, ret, why, nsig, nmiss = sim(g, [0], sld=1.0)
    assert why[0] == 1 and math.isclose(R[0], -3.0)


def test_fees_and_slippage_in_r():
    g = grid(o=[100, 100, 100, 100], h=[100, 100, 102, 100], l=[100, 100, 100, 100], c=[100, 100, 100, 100])
    ei, xi, ep, xp, sp, R, ret, why, *_ = sim(g, [0], sld=1.0, tpd=1.0, slip=0.0002, fee=0.0009)
    ent = 100 * 1.0002; px = (ent + 1.0) * (1 - 0.0002); pnl = px * (1 - 0.0009) - ent * 1.0009
    assert math.isclose(R[0], pnl / 1.0, rel_tol=1e-9) and R[0] < 1.0


def test_maker_fills_only_through_limit_and_counts_misses():
    # limite = fecho 100; low toca 100 mas não passa → não enche; expira após 3 barras
    g = grid(o=[100] * 6, h=[101] * 6, l=[100] * 6, c=[100] * 6)
    *_, R, ret, why, nsig, nmiss = sim(g, [0], sld=1.0, tpd=0.5, maker=True)
    assert len(R) == 0 and nsig == 1 and nmiss == 1
    g = grid(o=[100] * 6, h=[100, 100, 100.4, 100.6, 100, 100], l=[100, 100, 99.9, 100, 100, 100], c=[100] * 6)
    ei, xi, ep, xp, sp, R, ret, why, nsig, nmiss = sim(g, [0], sld=1.0, tpd=0.5, maker=True)
    assert ei[0] == 2 and ep[0] == 100 and xi[0] == 3 and why[0] == 0 and math.isclose(R[0], 0.5) and nmiss == 0


def test_maker_target_needs_trade_through():
    g = grid(o=[100] * 5, h=[100, 100, 100, 100.5, 100], l=[100, 99, 100, 100, 100], c=[100] * 5)
    *_, R, ret, why, nsig, nmiss = sim(g, [0], sld=2.0, tpd=0.5, maker=True, tstop=50)
    assert why[0] == 4                                   # high == alvo não chega para maker → só sai no fim


def test_time_stop_and_invalidation_exit_next_open():
    g = grid(o=[100, 100, 100, 100, 99, 99], h=[100] * 6, l=[99.5] * 6, c=[100, 100, 100, 99.8, 99, 99])
    ei, xi, ep, xp, sp, R, ret, why, *_ = sim(g, [0], sld=5.0, tstop=2)
    assert xi[0] == 3 and why[0] == 3
    inv = np.zeros(6, bool); inv[1] = True
    ei, xi, ep, xp, sp, R, ret, why, *_ = sim(g, [0], sld=5.0, tstop=50, inval=inv)
    assert xi[0] == 2 and why[0] == 2


def test_dynamic_target_uses_previous_bar_mid():
    g = grid(o=[100, 100, 100, 100], h=[100, 100, 101, 100], l=[100] * 4, c=[100] * 4)
    dyn = [np.nan, 105, 100.8, 100.8]
    ei, xi, ep, xp, sp, R, ret, why, *_ = sim(g, [0], sld=1.0, dyn=dyn)
    assert why[0] == 4                                   # na barra 2 o alvo é 105 (meio da barra 1), não 100,8 → não sai


def test_blocked_bars_no_entry():
    g = grid(o=[100] * 4, h=[101] * 4, l=[99.9] * 4, c=[100] * 4); b = np.ones(4, bool)
    *_, R, ret, why, nsig, nmiss = sim(g, [0, 1], sld=1.0, block=b)
    assert len(R) == 0 and nsig == 0


def test_signals_use_only_past():
    rng = np.random.default_rng(0); n = 1500
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n))); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.001; l = np.minimum(o, c) * 0.999; v = rng.uniform(1, 3, n)
    g = grid(o, h, l, c, v); g2 = {k: (x.copy() if isinstance(x, np.ndarray) else x) for k, x in g.items()}
    for k in ("o", "h", "l", "c"): g2[k][1000:] *= 1.5
    g2["v"][1000:] *= 9
    f, f2 = S.features(g), S.features(g2)
    for v_ in S.variants():
        a = S.signals(v_, g, f); b = S.signals(v_, g2, f2)
        assert np.array_equal(np.nan_to_num(a[0][:1000]), np.nan_to_num(b[0][:1000])), v_["id"]


def test_end_to_end_run_variant_and_stats():
    rng = np.random.default_rng(1); n = 4000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n))); o = np.r_[c[0], c[:-1]]
    g = grid(o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c, rng.uniform(1, 3, n)); f = S.features(g)
    for v in S.variants()[:4] + S.variants()[-4:]:
        T = S.merge([S.run_variant(v, g, f, int(g["ts"][0]), int(g["ts"][-1]) + S.M1)])
        st = S.stats(T, int(g["ts"][0]), int(g["ts"][0]) + S.D)
        assert st["trades"] == len(T["R"]) and np.all(T["stopdist"] > 0) and np.all(T["x_ts"] > T["e_ts"])


def test_account_day_halt_and_breaker():
    n = 6; e = S.DEV0 + np.arange(n) * 3_600_000
    T = {"e_ts": e, "x_ts": e + 60_000, "R": np.full(n, -1.0), "ret": np.full(n, -0.002), "stopdist": np.full(n, 0.002)}
    a = S.account(T)                                     # 1%/0,2% = 5× o saldo → limitado a 25% do saldo
    assert a["trades_taken"] == n and a["end_usd"] < 65
    T["ret"] = np.full(n, -0.04)                         # −1% da conta por trade (25% × −4%), composto
    a = S.account(T)                                     # 3 perdas = −2,97% (ainda não); a 4.ª passa de −3% → pausa o resto do dia
    assert a["day_halts"] == 1 and a["skipped_paused"] == 2 and a["trades_taken"] == 4


def test_regime_table():
    atr = np.array([0.1, 0.2, 0.5]); c = np.array([100.0, 100.0, 100.0])
    sl, tp = S.atr_regime(atr, c)
    assert np.allclose(sl, [0.1, 0.3, 1.0]) and np.allclose(tp, [0.15, 0.4, 1.5])


def test_variant_count_small():
    vs = S.variants(); assert len(vs) == 88 and len({v["id"] for v in vs}) == 88 and len(vs) <= 200


def test_prereg_hash_refuses_tampering(tmp_path):
    p = tmp_path / "pre.json"; doc = json.loads(json.dumps(S.prereg_doc()))
    doc["sha256"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest(); p.write_text(json.dumps(doc))
    assert S.check_prereg(str(p)) == doc["sha256"]
    doc["costs"]["taker_fee"] = 0.0; p.write_text(json.dumps(doc))
    with pytest.raises(SystemExit): S.check_prereg(str(p))


def test_committed_prereg_matches_code():
    S.check_prereg()


def test_holm_and_dsr():
    adj = S.holm(np.array([0.01, 0.04, 0.03])); assert math.isclose(adj[0], 0.03)
    rng = np.random.default_rng(2); x = rng.normal(0.001, 0.01, 400); srs = rng.normal(0, 0.05, 88)
    assert S.dsr_n(x, srs, 88) > S.dsr_n(x, srs, 7423)


def test_never_touches_live_or_keys():
    src = open(S.__file__).read() + open("desk/research/scalp_data.py").read()
    for bad in ("live.executor", "LiveBroker", "REVX_API_KEY", "private.pem", "place_order", "execution_mode: live", "DESK_RULES"):
        assert bad not in src
