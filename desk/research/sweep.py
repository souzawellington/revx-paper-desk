"""Sweep disciplinado (ideia vectorbt, motor numpy próprio) — espaço PRÉ-REGISTADO em DESK_RULES.md.
python -m desk.research.sweep [--out desk/state/research_sweep.json]
"""
from __future__ import annotations
import argparse, json, math, os, statistics
import numpy as np

H, D = 3_600_000, 86_400_000
DEV0 = 1697760000000          # 2023-10-20 00:00 UTC
HOLD0 = 1760918400000         # 2025-10-20 00:00 UTC
HOLD1 = 1792368000000         # 2026-10-18 00:00 UTC
SYMS = ["AAVE", "ADA", "AVAX", "BCH", "BTC", "DOGE", "DOT", "ETH", "LINK", "LTC", "NEAR", "SOL", "SUI", "UNI", "XRP"]
STOP = 0.08
SIDE_COST = 0.0009 + 0.001

GRID = ([("sma", f, s) for f, s in ((10, 50), (20, 100), (50, 200))] +
        [("donchian", n, m) for n, m in ((20, 10), (55, 20), (100, 50))] +
        [("tsmom", L, None) for L in (20, 60, 120)] +
        [("rsi", (n, lo), hi) for n, lo, hi in ((2, 10, 70), (14, 30, 55), (14, 25, 70))] +
        [("boll", n, k) for n, k in ((20, 2.0), (50, 2.5))])
TFS = (1, 4, 24)


def configs():
    def flat(*x):
        out = []
        for v in x:
            if v is None: continue
            out += list(v) if isinstance(v, tuple) else [v]
        return "_".join(str(v) for v in out)
    return [{"tf": tf, "fam": f, "a": a, "b": b, "id": f"{f}_{flat(a, b)}_{tf}h"} for tf in TFS for f, a, b in GRID]


# ---------- dados ----------
def load(data_dir, sym):
    p = os.path.join(data_dir, f"candles_{sym}-USD_60.json")
    if not os.path.exists(p): return None
    rows = sorted(json.load(open(p)), key=lambda c: c["start"])
    return {k: np.array([float(c[k]) for c in rows]) for k in ("start", "open", "high", "low", "close", "volume")}


def resample(d, tf):
    if tf == 1: return d
    b = (d["start"] // (tf * H)).astype(np.int64)
    idx = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    ends = np.r_[idx[1:], len(b)]
    return {"start": b[idx] * tf * H, "open": d["open"][idx], "close": d["close"][ends - 1],
            "high": np.maximum.reduceat(d["high"], idx), "low": np.minimum.reduceat(d["low"], idx),
            "volume": np.add.reduceat(d["volume"], idx)}


# ---------- indicadores (sem look-ahead: valor em t usa só ≤ t) ----------
def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.r_[0.0, x]); out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rolling(x, n, fn):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n); out[n - 1:] = fn(w, axis=1)
    return out


def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = np.zeros(len(c)), np.zeros(len(c)); out = np.full(len(c), np.nan)
    if len(c) <= n: return out
    au[n], ad[n] = up[1:n + 1].mean(), dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    rs = np.divide(au, ad, out=np.full(len(c), np.inf), where=ad > 0)
    out[n:] = 100 - 100 / (1 + rs[n:]); return out


def signal(d, cfg):
    """Estado desejado (0/1) no FECHO de cada barra. Regras de entrada/saída com histerese → máquina de estados."""
    c, f, a, b = d["close"], cfg["fam"], cfg["a"], cfg["b"]
    n = len(c); want = np.zeros(n, dtype=np.int8)
    if f == "sma":
        fa, sl = sma(c, a), sma(c, b); want = np.where(fa > sl, 1, 0).astype(np.int8); want[np.isnan(sl)] = 0; return want
    if f == "tsmom":
        r = np.full(n, np.nan); r[a:] = c[a:] / c[:-a] - 1; want = (r > 0).astype(np.int8); return want
    if f == "donchian":
        hi = np.r_[np.nan, rolling(d["high"], a, np.max)[:-1]]; lo = np.r_[np.nan, rolling(d["low"], b, np.min)[:-1]]
        ent, ex = c > hi, c < lo
    elif f == "rsi":
        r = rsi(c, a[0]); ent, ex = r < a[1], r > b
    elif f == "boll":
        m = sma(c, a); s = rolling(c, a, np.std); ent, ex = c < m - b * s, c > m
    st = 0
    for i in range(n):
        if st == 0 and ent[i]: st = 1
        elif st == 1 and ex[i]: st = 0
        want[i] = st
    return want


def simulate(d, want, t0, t1, side_cost=SIDE_COST, entry_cost=None, stop=STOP):
    """Executa `want` (decidido no fecho t) na abertura t+1. Devolve trades e retornos por barra (indexados por start).
    Só barras com start em [t0, t1); entradas só dentro da janela; posição aberta no fim fecha na abertura final."""
    ec = side_cost if entry_cost is None else entry_cost
    o, lo, st = d["open"], d["low"], d["start"]; n = len(o)
    ret = np.zeros(n); trades = []; i = 1; blocked = False
    inwin = (st >= t0) & (st < t1)
    while i < n:
        if not inwin[i]: i += 1; continue
        w = want[i - 1]
        if blocked and w == 0: blocked = False
        if w == 1 and not blocked:
            e = o[i]; sp = e * (1 - stop); j = i; px = None; why = None
            ret[i] -= ec
            while j < n and inwin[j]:
                if j > i and want[j - 1] == 0: px, why = o[j], "SIGNAL"; break
                if j > i and o[j] <= sp: px, why = o[j], "STOP_GAP"; break
                if lo[j] <= sp: px, why = sp, "STOP"; break
                j += 1
            if px is None:                                  # fim da janela
                j = min(j, n - 1); px, why = o[j], "END"
            # retornos barra-a-barra (open-to-open) nas barras detidas i..j-1; na barra de stop: stop/abertura
            if j > i: ret[i:j] += o[i + 1:j + 1] / o[i:j] - 1
            if why == "STOP": ret[j] += px / o[j] - 1
            ret[j if why != "END" else max(i, j - 1)] -= side_cost
            k = j + 1 if why == "STOP" else j
            if why.startswith("STOP"): blocked = True
            net = (px * (1 - side_cost)) / (e * (1 + ec)) - 1
            trades.append({"entry_ts": int(st[i]), "exit_ts": int(st[min(j, n - 1)]), "ret": net, "r": net / stop, "why": why})
            i = max(k, i + 1)
        else:
            i += 1
    return trades, ret


def daily(ret, start, t0, t1):
    """Agrega retornos por barra em retornos diários (composição) no intervalo [t0, t1)."""
    days = np.arange(t0, t1, D); out = np.zeros(len(days))
    di = ((start - t0) // D).astype(np.int64); m = (start >= t0) & (start < t1)
    lr = np.log1p(np.clip(ret, -0.999, None))
    np.add.at(out, di[m], lr[m]); return np.expm1(out)


def run_config(data, cfg, t0, t1, **kw):
    """Carteira de 15 sleeves (1/N), retornos diários + trades agregados."""
    dly, trades = [], []
    for sym, d1 in data.items():
        d = resample(d1, cfg["tf"]); want = signal(d, cfg)
        tr, r = simulate(d, want, t0, t1, **kw); trades += [{**t, "sym": sym} for t in tr]
        dly.append(daily(r, d["start"], t0, t1))
    return np.mean(dly, axis=0), trades


def buy_hold(data, t0, t1):
    dly = []
    for d in data.values():
        r = np.zeros(len(d["open"])); r[:-1] = d["open"][1:] / d["open"][:-1] - 1; dly.append(daily(r, d["start"], t0, t1))
    return np.mean(dly, axis=0)


# ---------- métricas ----------
def sharpe(x):
    s = x.std(ddof=1); return float(x.mean() / s * math.sqrt(365)) if s > 0 else 0.0


def max_dd(x):
    eq = np.cumprod(1 + x); pk = np.maximum.accumulate(eq); return float(((pk - eq) / pk).max()) if len(x) else 0.0


def trade_stats(trades):
    n = len(trades); rs = [t["r"] for t in trades]
    return {"n": n, "win_rate": sum(r > 0 for r in rs) / n if n else 0.0, "expectancy_r": sum(rs) / n if n else 0.0}


def deflated_sharpe(best_daily, all_sr_daily):
    """DSR (Bailey & López de Prado 2014). SR em unidades por-período (diário, não anualizado)."""
    nd = statistics.NormalDist(); x = best_daily; T = len(x); N = len(all_sr_daily)
    sr = x.mean() / x.std(ddof=1); g3 = float(((x - x.mean()) ** 3).mean() / x.std() ** 3); g4 = float(((x - x.mean()) ** 4).mean() / x.std() ** 4)
    v = float(np.var(all_sr_daily, ddof=1)); em = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - em) * nd.inv_cdf(1 - 1 / N) + em * nd.inv_cdf(1 - 1 / (N * math.e)))
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return {"dsr": nd.cdf(z), "sr_daily": float(sr), "sr0_daily": sr0, "skew": g3, "kurt": g4, "N": N, "T": T}


def stationary_bootstrap_idx(T, mean_block, rng):
    p = 1.0 / mean_block; idx = np.empty(T, dtype=np.int64); idx[0] = rng.integers(T)
    jumps = rng.random(T) < p; starts = rng.integers(T, size=T)
    for t in range(1, T): idx[t] = starts[t] if jumps[t] else (idx[t - 1] + 1) % T
    return idx


def reality_check(R, B=2000, mean_block=10, seed=7):
    """White (2000): R = matriz (k configs × T) de retornos diferenciais vs benchmark. H0: nenhum tem média > 0."""
    rng = np.random.default_rng(seed); k, T = R.shape; mu = R.mean(axis=1)
    V = math.sqrt(T) * mu.max(); cnt = 0
    for _ in range(B):
        idx = stationary_bootstrap_idx(T, mean_block, rng)
        Vb = math.sqrt(T) * (R[:, idx].mean(axis=1) - mu).max()
        cnt += Vb >= V
    return {"V": float(V), "p": cnt / B, "B": B}


def walk_forward(dly_by_cfg, days, train_d=365, test_d=91):
    """Dentro do DEV: escolhe o maior Sharpe nos 12 meses anteriores, aplica nos 3 meses seguintes."""
    out, picks = [], []; s = 0; T = len(days)
    while s + train_d + test_d <= T:
        tr = slice(s, s + train_d); te = slice(s + train_d, s + train_d + test_d)
        best = max(dly_by_cfg, key=lambda k: sharpe(dly_by_cfg[k][tr])); picks.append(best)
        out.append(dly_by_cfg[best][te]); s += test_d
    x = np.concatenate(out) if out else np.zeros(0)
    return {"oos_sharpe": sharpe(x) if len(x) > 2 else 0.0, "oos_ret": float(np.prod(1 + x) - 1) if len(x) else 0.0,
            "picks": picks, "folds": len(out), "max_dd": max_dd(x)}


def load_all(data_dir):
    out = {}
    for s in SYMS:
        d = load(data_dir, s)
        if d is not None and len(d["open"]) > 500: out[s] = d
    return out


def auditor(ts, dd, rules):
    return {"n": bool(ts["n"] >= rules.threshold_trades), "wr": bool(ts["win_rate"] >= rules.threshold_win_rate),
            "exp": bool(ts["expectancy_r"] >= rules.threshold_expectancy_r), "dd": bool(dd <= rules.threshold_max_dd)}


def main():
    from desk.rules import load_rules
    ap = argparse.ArgumentParser(); ap.add_argument("--cb", default="data_ext/coinbase"); ap.add_argument("--rx", default="data")
    ap.add_argument("--out", default="desk/state/research_sweep.json"); a = ap.parse_args(); rules = load_rules()
    cb, rx = load_all(a.cb), load_all(a.rx)
    cfgs = configs(); days = np.arange(DEV0, HOLD0, D)
    dev = {}; dev_tr = {}
    for c in cfgs:
        x, tr = run_config(cb, c, DEV0, HOLD0); dev[c["id"]] = x; dev_tr[c["id"]] = tr
    bh_dev = buy_hold(cb, DEV0, HOLD0)
    srs = {k: sharpe(v) for k, v in dev.items()}
    best = max(srs, key=srs.get)
    dsr = deflated_sharpe(dev[best], np.array([v.mean() / v.std(ddof=1) if v.std() > 0 else 0 for v in dev.values()]))
    M = np.array([dev[k] for k in dev])
    rc_cash = reality_check(M); rc_bh = reality_check(M - bh_dev)
    wf = walk_forward(dev, days)
    edge_dev = dsr["dsr"] > 0.95 and rc_cash["p"] < 0.05
    cfg = next(c for c in cfgs if c["id"] == best)
    # spec 13 escrita mecanicamente ANTES do holdout
    os.makedirs("desk/strategies", exist_ok=True)
    open("desk/strategies/13_sweep_best.md", "w").write(
        f"# 13 — sweep_best (selecção mecânica pré-registada)\nConfig: `{best}` (maior Sharpe no DEV 2023-10-20→2025-10-19, entre N=42).\n"
        f"Avaliada uma vez no HOLDOUT 2025-10-20→2026-10-18 (Coinbase) e na Revolut X. Custos 0.19%/lado, stop −8%, R = retorno/8%.\n")
    hold, hold_tr = run_config(cb, cfg, HOLD0, HOLD1); rxh, rx_tr = run_config(rx, cfg, HOLD0, HOLD1)
    mk, mk_tr = run_config(cb, cfg, HOLD0, HOLD1, entry_cost=0.0005)
    bh_h = buy_hold(cb, HOLD0, HOLD1); bh_rx = buy_hold(rx, HOLD0, HOLD1)
    top = sorted(srs, key=srs.get, reverse=True)
    hold_all = {}
    for c in cfgs:        # diagnóstico: todas no holdout (NÃO usado para selecção)
        x, tr = run_config(cb, c, HOLD0, HOLD1); hold_all[c["id"]] = {"sharpe": sharpe(x), "ret": float(np.prod(1 + x) - 1), **trade_stats(tr)}
    ts_h, ts_rx = trade_stats(hold_tr), trade_stats(rx_tr)
    aud = auditor(ts_h, max_dd(hold), rules)
    validated = edge_dev and all(aud.values()) and ts_rx["expectancy_r"] > 0
    res = {"N": len(cfgs), "best": best, "dev": {"sharpe": srs[best], "ret": float(np.prod(1 + dev[best]) - 1), "max_dd": max_dd(dev[best]),
                                                 **trade_stats(dev_tr[best])},
           "dev_top5": [(k, round(srs[k], 3), round(trade_stats(dev_tr[k])["expectancy_r"], 4)) for k in top[:5]],
           "dev_bh": {"sharpe": sharpe(bh_dev), "ret": float(np.prod(1 + bh_dev) - 1), "max_dd": max_dd(bh_dev)},
           "dsr": dsr, "rc_vs_cash": rc_cash, "rc_vs_bh": rc_bh, "walk_forward": wf, "edge_dev": edge_dev,
           "holdout_cb": {"sharpe": sharpe(hold), "ret": float(np.prod(1 + hold) - 1), "max_dd": max_dd(hold), **ts_h, "auditor": aud},
           "holdout_cb_maker_entry_sens": {"sharpe": sharpe(mk), "ret": float(np.prod(1 + mk) - 1), **trade_stats(mk_tr)},
           "holdout_rx": {"sharpe": sharpe(rxh), "ret": float(np.prod(1 + rxh) - 1), "max_dd": max_dd(rxh), **ts_rx},
           "holdout_bh": {"cb_sharpe": sharpe(bh_h), "cb_ret": float(np.prod(1 + bh_h) - 1), "cb_dd": max_dd(bh_h),
                          "rx_ret": float(np.prod(1 + bh_rx) - 1)},
           "holdout_all_diagnostic": hold_all,
           "frac_dev_sharpe_pos": sum(v > 0 for v in srs.values()) / len(srs),
           "dev_all": {k: round(v, 3) for k, v in srs.items()},
           "finding": "DATA_VALIDATED" if validated else ("TRADE_OFF" if ts_h["n"] >= rules.threshold_trades else "NO_EDGE")}
    json.dump(res, open(a.out, "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k not in ("holdout_all_diagnostic", "dev_all")}, indent=1, default=float))


if __name__ == "__main__":
    main()
