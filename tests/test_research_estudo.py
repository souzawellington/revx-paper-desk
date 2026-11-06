"""Testes do estudo multi-estratégia (desk/research/estudo.py) e do regime (desk/research/regime.py). Dados sintéticos."""
import json, math
import numpy as np
import pytest
from desk.research import estudo as E

D = E.D


def panel(close, low=None, opn=None, qv=None, syms=None, t0=1_600_000_000_000 // D * D):
    c = np.array(close, float)
    if c.ndim == 1: c = c[:, None]
    T, A = c.shape
    o = c.copy() if opn is None else np.array(opn, float).reshape(T, A)
    lo = np.minimum(o, c) if low is None else np.array(low, float).reshape(T, A)
    return {"ts": t0 + np.arange(T, dtype=np.int64) * D, "syms": syms or [f"S{i}" for i in range(A)], "open": o,
            "high": np.maximum(o, c), "low": lo, "close": c, "qv": np.ones((T, A)) if qv is None else np.array(qv, float)}


def run(P, W, reb=None, cost=0.0, stop=0.0, reentry=14):
    reb = np.ones(len(P["ts"]), bool) if reb is None else reb
    return E.run_sim(P, W, reb, int(P["ts"][0]), int(P["ts"][-1]) + D, cost=cost, stop=stop, reentry=reentry)


def test_signal_executes_next_open_no_lookahead():
    c = [100, 100, 100, 110, 121, 121]
    P = panel(c, opn=[100, 100, 100, 110, 121, 121]); W = np.zeros((6, 1)); W[2:, 0] = 1.0   # sinal no fecho do dia 2
    s = run(P, W)
    assert np.allclose(s["eq"][:3], 1.0)                 # dia 2 ainda em caixa (ordem só na abertura do dia 3)
    assert s["tr_in"][0] == 3 and math.isclose(s["eq"][4], 1.1, rel_tol=1e-9)   # comprou a 110, vale 121


def test_round_trip_costs():
    P = panel([100] * 6); W = np.zeros((6, 1)); W[0:2, 0] = 1.0
    s = run(P, W, cost=0.0019)
    assert len(s["tr_ret"]) == 1
    assert math.isclose(s["tr_ret"][0], (1 - 0.0019) / (1 + 0.0019) - 1, rel_tol=1e-9)


def test_stop_minus_8pct_and_reentry_block():
    c = [100, 100, 95, 95, 95, 95, 95, 95]; lo = [100, 100, 90, 95, 95, 95, 95, 95]
    P = panel(c, low=lo, opn=[100, 100, 100, 95, 95, 95, 95, 95]); W = np.ones((8, 1))
    s = run(P, W, stop=0.08, reentry=3)
    assert s["tr_why"][0] == 1 and math.isclose(s["tr_ret"][0], -0.08, rel_tol=1e-9)
    assert s["tr_in"][1] - s["tr_out"][0] >= 3           # bloqueado até passar o período de reentrada


def test_gap_below_stop_fills_at_open():
    P = panel([100, 100, 80, 80], low=[100, 100, 79, 80], opn=[100, 100, 82, 80]); W = np.ones((4, 1))
    s = run(P, W, stop=0.08)
    assert math.isclose(s["tr_ret"][0], -0.18, rel_tol=1e-9)


def test_delisting_forces_exit_at_last_close():
    c = np.array([[100.0], [100.0], [100.0], [50.0], [np.nan], [np.nan]])
    P = panel(c, opn=c, low=c); W = np.ones((6, 1))
    s = run(P, W)
    assert s["tr_why"][0] == 2 and math.isclose(s["tr_ret"][0], -0.5, rel_tol=1e-9) and math.isclose(s["eq"][-1], 0.5)


def test_universe_point_in_time_and_min_history():
    T = 200; c = np.ones((T, 2)) * 10; qv = np.ones((T, 2)); qv[150:, 1] = 1e9; c[:100, 1] = np.nan
    P = panel(c, qv=qv)
    U = E.universe(P, topn=1, volwin=30, min_hist=120)
    assert not U[:219, 1].any()                          # 1ª barra no dia 100 → só elegível com 120 barras (dia 219)
    assert U[149, 0] and not U[149, 1]                   # volume futuro (dia 150+) não influencia o passado


def test_desk_caps():
    W = np.array([[0.3, 0.2, 0.2, 0.1, 0.1, 0.05, 0.05]])
    out = E.desk_caps(W)
    assert out.max() <= 0.125 + 1e-12 and (out > 0).sum() == 5


def test_holm_and_neighbours():
    adj = E.holm(np.array([0.01, 0.04, 0.03]))
    assert np.all(adj >= np.array([0.01, 0.04, 0.03])) and math.isclose(adj[0], 0.03)
    vs = E.variants(); v = next(x for x in vs if x["id"] == "C1_tsmom:L=60,rebd=7")
    ids = {u["id"] for u in E.neighbours(v, vs)}
    assert ids == {"C1_tsmom:L=30,rebd=7", "C1_tsmom:L=90,rebd=7", "C1_tsmom:L=60,rebd=1"}


def test_variant_count_and_families():
    vs = E.variants()
    assert len(vs) == 77 and len(E.FAMILIES) == 7 and len({v["id"] for v in vs}) == 77


def test_prereg_hash_refuses_tampering(tmp_path):
    p = tmp_path / "pre.json"; doc = E.prereg_doc()
    import hashlib
    blob = json.dumps(doc, sort_keys=True); doc["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    p.write_text(json.dumps(doc)); assert E.check_prereg(str(p)) == doc["sha256"]
    doc["costs"]["base_per_side"] = 0.0; p.write_text(json.dumps(doc))
    with pytest.raises(SystemExit): E.check_prereg(str(p))


def test_committed_prereg_matches_code():
    E.check_prereg()                                     # o ficheiro versionado bate com o código (grelha não mudou)


def test_strategy_weights_use_only_past():
    """Mudar preços FUTUROS não altera pesos passados (todas as famílias diárias)."""
    rng = np.random.default_rng(0); T, A = 400, 12
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, (T, A)), axis=0)); syms = ["BTC", "ETH"] + [f"S{i}" for i in range(A - 2)]
    P = panel(c, qv=rng.uniform(1, 2, (T, A)), syms=syms); P["high"] = c * 1.01; P["low"] = c * 0.99
    P2 = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    for k in ("open", "high", "low", "close"): P2[k][300:] *= 3.0
    P2["qv"][300:] *= 50
    for v in E.variants():
        if v["fam"] == "C5_reversao_4h": continue
        U, U2 = E.universe(P), E.universe(P2)
        W1, _ = E.weights(v, P, U); W2, _ = E.weights(v, P2, U2)
        assert np.allclose(np.nan_to_num(W1[:300]), np.nan_to_num(W2[:300])), v["id"]


def test_meanrev_weights_past_only_and_bounded():
    rng = np.random.default_rng(1); T = 800
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (T, 3)), axis=0)); P4 = panel(c)
    W, _ = E.s_meanrev(P4, 10, 1, 70); c2 = c.copy(); c2[500:] *= 0.5; W2, _ = E.s_meanrev(panel(c2), 10, 1, 70)
    assert np.allclose(W[:500], W2[:500]) and W.sum(axis=1).max() <= 1 + 1e-12


def test_study_never_touches_live_or_keys():
    src = open(E.__file__).read() + open("desk/research/regime.py").read() + open("desk/research/binance_vision.py").read()
    for bad in ("live.executor", "LiveBroker", "REVX_API_KEY", "private.pem", "place_order", "execution_mode: live"):
        assert bad not in src
    from desk.rules import load_rules
    r = load_rules(); mode = getattr(r, "execution_mode", None) or (getattr(r, "raw", {}) or {}).get("execution_mode")
    lines = [l.strip() for l in open("desk/DESK_RULES.md") if l.strip().startswith("execution_mode:")]
    assert lines and all(l != "execution_mode: live" for l in lines) and mode != "live"


def test_regime_asset_stats():
    from desk.research.regime import asset_stats
    c = np.linspace(100, 200, 400)
    s = asset_stats(c)
    assert s["above_sma200"] and s["ret30d"] > 0 and s["dd_from_1y_high"] == 0.0 and 0 <= s["rv30_pctile_hist"] <= 1


def test_binance_vision_parse_microseconds():
    import io, zipfile
    from desk.research.binance_vision import parse_zip
    b = io.BytesIO(); z = zipfile.ZipFile(b, "w")
    z.writestr("x.csv", "1735689600000000,1,2,0.5,1.5,10,1735775999999999,15,1,1,1,0\n1704067200000,1,2,0.5,1.5,10,0,15,1,1,1,0\n"); z.close()
    rows = parse_zip(b.getvalue())
    assert rows[0]["start"] == 1735689600000 and rows[1]["start"] == 1704067200000 and rows[0]["quote_volume"] == 15


def test_split_relistings_separates_reused_ticker():
    r = [{"start": i * D, "close": 1.0} for i in range(5)] + [{"start": (20 + i) * D, "close": 9.0} for i in range(3)]
    out = E.split_relistings({"LUNA": r})
    assert set(out) == {"LUNA", "LUNA~2"} and len(out["LUNA"]) == 5 and out["LUNA~2"][0]["close"] == 9.0
