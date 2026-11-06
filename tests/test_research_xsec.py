import pathlib, re
import numpy as np, pytest
from desk.research import xsec_ml as X, sweep as S


def panel(T=200, N=6, seed=0):
    rng = np.random.default_rng(seed); c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), axis=0))
    o = np.vstack([c[:1], c[:-1]]); P = {"open": o, "close": c, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
                                          "volume": rng.uniform(1, 2, (T, N))}
    return P


def test_features_no_lookahead():
    P = panel(); _, F = X.features(P)
    Pt = {k: v[:150] for k, v in P.items()}; _, Ft = X.features(Pt)
    np.testing.assert_allclose(np.nan_to_num(F[:150]), np.nan_to_num(Ft), atol=1e-9)


def test_label_is_open_t1_to_open_t2():
    P = panel(); y = X.labels(P)
    assert y[10, 2] == pytest.approx(P["open"][12, 2] / P["open"][11, 2] - 1) and np.isnan(y[-1]).all()


def test_ic_perfect_predictor():
    P = panel(); y = X.labels(P); rows = np.zeros(len(y), bool); rows[70:190] = True
    st = X.ic_stats(y.copy(), y, rows); assert st["ic"]["mean"] == pytest.approx(1.0) and st["rank_ic"]["mean"] == pytest.approx(1.0)


def test_topk_costs_and_stop():
    T, N = 20, 4; o = np.full((T, N), 100.0); P = {"open": o, "low": o * 0.99, "high": o * 1.01, "close": o, "volume": np.ones((T, N))}
    P["low"][6, 0] = 90.0                                   # par 0 toca o stop no dia 6
    pred = np.tile(np.array([3.0, 2.0, 1.0, 0.0]), (T, 1)); rows = np.zeros(T, bool); rows[5:10] = True
    r = X.topk_backtest(pred, P, rows, k=1)
    assert r["n"] == 1 and r["expectancy_r"] == pytest.approx((92 * (1 - S.SIDE_COST) / (100 * (1 + S.SIDE_COST)) - 1) / 0.08)
    r2 = X.topk_backtest(pred, P, rows, k=1, stop=9)          # sem stop: preço plano → só custos
    assert r2["ret"] < 0 and r2["n"] == 1


def test_fallback_model_runs_without_lightgbm_and_split_is_time_ordered():
    P = panel(T=300); _, F = X.features(P); y = X.labels(P); yr = X.cs_rank(y)
    tr = np.zeros(300, bool); tr[60:200] = True; va = np.zeros(300, bool); va[202:250] = True; te = np.zeros(300, bool); te[252:298] = True
    pred, info = X.fit_predict(F, yr, tr, va, te); assert pred.shape == y.shape and info["model"] in ("lightgbm", "ridge_fallback")
    assert X.TRAIN1 < S.HOLD0 and S.DEV0 < X.TRAIN1


def test_research_never_touches_orders_or_credentials():
    src = "\n".join(p.read_text() for p in pathlib.Path("desk/research").glob("*.py"))
    assert not re.search(r"place_order|place_tpsl|cancel_order|cancel_all|REVX_API_KEY|private\.pem|apiKey\s*=", src)
