"""Ranking cross-sectional diário estilo qlib (Alpha158 subset + LightGBM), re-implementado sem pyqlib.
PRÉ-REGISTADO em DESK_RULES.md. python -m desk.research.xsec_ml  (LightGBM no venv /workspace/.venv-research;
sem lightgbm usa ridge numpy — só para testes).
"""
from __future__ import annotations
import argparse, json, math
import numpy as np
from . import sweep as S

D = S.D
TRAIN1 = 1745020800000   # 2025-04-19 00:00 UTC (fim treino, exclusivo)
WINDOWS = (5, 10, 20, 30, 60)
TOPK = 3
LGB_PARAMS = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 15, "max_depth": 4, "min_data_in_leaf": 50,
              "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 10.0, "verbose": -1, "seed": 7}


def daily_panel(data):
    """{sym: daily ohlcv} alinhado num calendário comum (dias UTC presentes em todos os pares → NaN se faltar)."""
    dd = {s: S.resample(d, 24) for s, d in data.items()}
    days = np.unique(np.concatenate([d["start"] for d in dd.values()]))
    P = {k: np.full((len(days), len(dd)), np.nan) for k in ("open", "high", "low", "close", "volume")}
    for j, d in enumerate(dd.values()):
        ix = np.searchsorted(days, d["start"])
        for k in P: P[k][ix, j] = d[k]
    return days, list(dd), P


def _roll(x, w, fn):
    out = np.full_like(x, np.nan)
    if len(x) >= w:
        v = np.lib.stride_tricks.sliding_window_view(x, w, axis=0)       # (T-w+1, N, w)
        out[w - 1:] = fn(v, axis=-1)
    return out


def features(P):
    """Alpha158 (subset): valores no dia t usam só dados ≤ fecho de t."""
    o, h, l, c, v = (P[k] for k in ("open", "high", "low", "close", "volume")); F = {}
    F["KMID"] = (c - o) / o; F["KLEN"] = (h - l) / o; F["KUP"] = (h - np.maximum(o, c)) / o
    F["KLOW"] = (np.minimum(o, c) - l) / o; F["KSFT"] = (2 * c - h - l) / o
    lv = np.log1p(v)
    for w in WINDOWS:
        sh = np.full_like(c, np.nan); sh[w:] = c[:-w]
        F[f"ROC{w}"] = sh / c; F[f"MA{w}"] = _roll(c, w, np.mean) / c; F[f"STD{w}"] = _roll(c, w, np.std) / c
        mx, mn = _roll(h, w, np.max), _roll(l, w, np.min)
        F[f"MAX{w}"] = mx / c; F[f"MIN{w}"] = mn / c; F[f"RSV{w}"] = (c - mn) / (mx - mn + 1e-12)
        F[f"VMA{w}"] = _roll(v, w, np.mean) / (v + 1e-12); F[f"VSTD{w}"] = _roll(v, w, np.std) / (v + 1e-12)
        cc = np.full_like(c, np.nan)
        if len(c) >= w:
            a = np.lib.stride_tricks.sliding_window_view(c, w, axis=0); b = np.lib.stride_tricks.sliding_window_view(lv, w, axis=0)
            am, bm = a - a.mean(-1, keepdims=True), b - b.mean(-1, keepdims=True)
            cc[w - 1:] = (am * bm).sum(-1) / np.sqrt((am ** 2).sum(-1) * (bm ** 2).sum(-1) + 1e-12)
        F[f"CORR{w}"] = cc
    names = sorted(F); X = np.stack([F[k] for k in names], axis=-1)            # (T, N, F)
    # z-score cross-sectional por dia (robusto a níveis diferentes entre pares)
    mu = np.nanmean(X, axis=1, keepdims=True); sd = np.nanstd(X, axis=1, keepdims=True)
    return names, (X - mu) / (sd + 1e-12)


def labels(P):
    """Retorno abertura t+1 → abertura t+2 (decisão no fecho de t)."""
    o = P["open"]; y = np.full_like(o, np.nan); y[:-2] = o[2:] / o[1:-1] - 1; return y


def cs_rank(y):
    r = np.full_like(y, np.nan)
    for t in range(len(y)):
        m = ~np.isnan(y[t])
        if m.sum() >= 3: r[t, m] = (np.argsort(np.argsort(y[t, m])) + 0.5) / m.sum()
    return r


def flat(X, y, rows):
    xs, ys = X[rows].reshape(-1, X.shape[-1]), y[rows].reshape(-1)
    m = ~np.isnan(ys) & ~np.isnan(xs).any(axis=1); return xs[m], ys[m]


def fit_predict(X, yr, tr, va, te):
    xtr, ytr = flat(X, yr, tr); xva, yva = flat(X, yr, va)
    try:
        import lightgbm as lgb
        m = lgb.train(LGB_PARAMS, lgb.Dataset(xtr, ytr), 500, valid_sets=[lgb.Dataset(xva, yva)],
                      callbacks=[lgb.early_stopping(50, verbose=False)])
        pred = lambda Z: m.predict(np.nan_to_num(Z.reshape(-1, Z.shape[-1]))).reshape(Z.shape[:2])
        info = {"model": "lightgbm", "best_iter": m.best_iteration}
    except ImportError:
        A = xtr.T @ xtr + 10.0 * np.eye(xtr.shape[1]); w = np.linalg.solve(A, xtr.T @ (ytr - 0.5))
        pred = lambda Z: np.nan_to_num(Z) @ w + 0.5; info = {"model": "ridge_fallback"}
    return pred(X), info


def ic_stats(pred, y, rows):
    ics, rics = [], []
    for t in np.flatnonzero(rows):
        m = ~np.isnan(y[t]) & ~np.isnan(pred[t])
        if m.sum() < 5: continue
        p, q = pred[t, m], y[t, m]
        if p.std() == 0 or q.std() == 0: continue
        ics.append(np.corrcoef(p, q)[0, 1])
        rp, rq = np.argsort(np.argsort(p)), np.argsort(np.argsort(q)); rics.append(np.corrcoef(rp, rq)[0, 1])
    ics, rics = np.array(ics), np.array(rics); n = len(ics)
    f = lambda a: {"mean": float(a.mean()), "ir": float(a.mean() / a.std(ddof=1)), "t": float(a.mean() / a.std(ddof=1) * math.sqrt(len(a)))} if len(a) > 2 else {}
    return {"days": n, "ic": f(ics), "rank_ic": f(rics)}


def topk_backtest(pred, P, rows, k=TOPK, side=S.SIDE_COST, stop=S.STOP):
    """Top-k long-only: escolhe no fecho t, detém de abertura t+1 a abertura t+2 (segmentos contíguos = 1 trade).
    Stop −8% desde a entrada do segmento (mínima diária); após stop o par fica bloqueado até sair do top-k."""
    o, lo = P["open"], P["low"]; T, N = o.shape; idx = np.flatnonzero(rows)
    held = {}; blocked = set(); trades = []; dret = []
    for t in idx:
        if t + 2 >= T: break
        p = pred[t].copy(); p[np.isnan(o[t + 1]) | np.isnan(o[t + 2])] = -np.inf
        top = set(np.argsort(-p)[:k]) if np.isfinite(p).sum() >= k else set()
        blocked &= top; r = 0.0
        for j in list(held):                                   # saídas por sinal na abertura t+1
            if j not in top:
                e = held.pop(j); px = o[t + 1, j]; trades.append((px * (1 - side)) / (e * (1 + side)) - 1)
                r -= side / k
        for j in top:
            if j in blocked: continue
            if j not in held: held[j] = o[t + 1, j]; r -= side / k
            e, a, b = held[j], o[t + 1, j], o[t + 2, j]
            if lo[t + 1, j] <= e * (1 - stop):                 # stop durante o dia t+1
                px = min(a, e * (1 - stop)); r += (px / a - 1) / k - side / k
                trades.append((px * (1 - side)) / (e * (1 + side)) - 1); held.pop(j); blocked.add(j)
            else:
                r += (b / a - 1) / k
        dret.append(r)
    for j, e in held.items():
        trades.append((o[min(idx[-1] + 2, T - 1), j] * (1 - side)) / (e * (1 + side)) - 1)
    x = np.array(dret); rs = np.array(trades) / stop
    return {"days": len(x), "sharpe": S.sharpe(x) if len(x) > 2 else 0.0, "ret": float(np.prod(1 + x) - 1), "max_dd": S.max_dd(x),
            "n": len(rs), "win_rate": float((rs > 0).mean()) if len(rs) else 0.0, "expectancy_r": float(rs.mean()) if len(rs) else 0.0}


def ew_bh(P, rows):
    o = P["open"]; idx = np.flatnonzero(rows); idx = idx[idx + 2 < len(o)]
    x = np.nanmean(o[idx + 2] / o[idx + 1] - 1, axis=1); return {"sharpe": S.sharpe(x), "ret": float(np.prod(1 + x) - 1), "max_dd": S.max_dd(x)}


def main():
    from desk.rules import load_rules
    ap = argparse.ArgumentParser(); ap.add_argument("--cb", default="data_ext/coinbase"); ap.add_argument("--rx", default="data")
    ap.add_argument("--out", default="desk/state/research_xsec.json"); a = ap.parse_args(); rules = load_rules()
    days, syms, P = daily_panel(S.load_all(a.cb)); names, X = features(P); y = labels(P); yr = cs_rank(y)
    tr = (days >= S.DEV0 + 60 * D) & (days < TRAIN1 - 2 * D)       # sem sobreposição do label com a validação
    va = (days >= TRAIN1) & (days < S.HOLD0 - 2 * D); te = (days >= S.HOLD0) & (days < S.HOLD1)
    pred, info = fit_predict(X, yr, tr, va, te)
    res = {"features": len(names), "pairs": syms, **info, "ic_valid": ic_stats(pred, y, va), "ic_test": ic_stats(pred, y, te),
           "top3_test": topk_backtest(pred, P, te), "ew_bh_test": ew_bh(P, te), "top3_valid": topk_backtest(pred, P, va)}
    # segundo holdout: Revolut X (modelo treinado na Coinbase, features da Revolut X)
    rdays, rsyms, RP = daily_panel(S.load_all(a.rx)); _, RX = features(RP)
    rpred = None
    try:
        import lightgbm  # noqa
        xtr, ytr = flat(X, yr, tr); xva, yva = flat(X, yr, va)
        import lightgbm as lgb
        m = lgb.train(LGB_PARAMS, lgb.Dataset(xtr, ytr), 500, valid_sets=[lgb.Dataset(xva, yva)], callbacks=[lgb.early_stopping(50, verbose=False)])
        rpred = m.predict(np.nan_to_num(RX.reshape(-1, RX.shape[-1]))).reshape(RX.shape[:2])
    except ImportError:
        pass
    if rpred is not None:
        rte = (rdays >= S.HOLD0) & (rdays < S.HOLD1); ry = labels(RP)
        res["rx_ic_test"] = ic_stats(rpred, ry, rte); res["rx_top3_test"] = topk_backtest(rpred, RP, rte); res["rx_ew_bh"] = ew_bh(RP, rte)
    t3 = res["top3_test"]
    ok = (t3["n"] >= rules.threshold_trades and t3["win_rate"] >= rules.threshold_win_rate and t3["expectancy_r"] >= rules.threshold_expectancy_r
          and t3["max_dd"] <= rules.threshold_max_dd and res.get("rx_top3_test", {}).get("expectancy_r", -1) > 0)
    res["finding"] = "DATA_VALIDATED" if ok else ("TRADE_OFF" if t3["n"] >= rules.threshold_trades else "NO_EDGE")
    json.dump(res, open(a.out, "w"), indent=1, default=float); print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
