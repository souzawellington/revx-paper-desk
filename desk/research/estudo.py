"""Estudo multi-estratégia (prompt "elite quant"): ≥6 candidatas long-only spot, eliminação por testes, só sobreviventes vão a paper.
Disciplina:
  * dados diários PÚBLICOS data.binance.vision (inclui pares deslistados) + 1H BTC/ETH/SOL para a média-reversão 4H;
  * universo point-in-time: top-10 por volume em USDT dos 30 dias anteriores (só passado), mín. 120 dias de histórico;
  * sinal no FECHO do dia t → execução na ABERTURA de t+1 (sem look-ahead); stop −8% do preço médio (regra do desk);
  * custos: 0,09% taker + 0,10% slippage por lado (base); 2× (0,38%/lado); maker (0% + 0,05% seleção adversa) como sensibilidade;
  * grelha + regra de selecção + critérios de validação PRÉ-REGISTADOS em desk/research/prereg_estudo.json (SHA-256)
    ANTES do holdout; `run` recusa se o hash não bater; holdout avaliado UMA vez para o campeão IS de cada família;
  * DSR (N = variantes deste estudo e N acumulado do projecto) + White Reality Check sobre TODAS as variantes.
python -m desk.research.estudo prereg | run | regime
Nada aqui toca execution_mode, live/, chaves ou limiares do auditor.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json, math, os
import numpy as np

try:
    from numba import njit
except Exception:                       # venv do desk/testes: Python puro, mesmos resultados
    def njit(*a, **k):
        if a and callable(a[0]): return a[0]
        return lambda f: f

D, H = 86_400_000, 3_600_000
DIR_1D, DIR_1H = "data_ext/binance_vision/1d", "data_ext/binance_vision/1h"
STATE = "desk/state/estudo_estrategias"
PREREG = "desk/research/prereg_estudo.json"
IS0, SPLIT, OOS1 = 1514764800000, 1672531200000, 1790812800000   # 2018-01-01 | 2023-01-01 | 2026-10-01 (excl.)
COST, COST2X, MAKER = 0.0019, 0.0038, 0.0005
STOP, REENTRY_D = 0.08, 14
BAND_ABS, BAND_REL = 0.01, 0.20
TOPN, MIN_HIST, VOLWIN = 10, 120, 30
PRIOR_TRIALS = 7200 + 42 + 1 + 15        # exitgrid + sweep + presample + specs anteriores (aprox., declarado)


# ---------------- dados ----------------
def load_panel(d=DIR_1D, syms=None, bar=D):
    files = sorted(f for f in os.listdir(d) if f.endswith(".json") and f != "manifest.json")
    syms = syms or [f[:-5] for f in files]
    raw = {s: json.load(open(os.path.join(d, f"{s}.json"))) for s in syms if os.path.exists(os.path.join(d, f"{s}.json"))}
    if bar == D: raw = split_relistings(raw)
    t0 = min(r[0]["start"] for r in raw.values()); t1 = max(r[-1]["start"] for r in raw.values())
    ts = np.arange(t0 // bar * bar, t1 + bar, bar, dtype=np.int64); T, A = len(ts), len(raw)
    P = {k: np.full((T, A), np.nan) for k in ("open", "high", "low", "close", "qv")}
    for j, (s, rows) in enumerate(raw.items()):
        for r in rows:
            i = (r["start"] - ts[0]) // bar
            if 0 <= i < T and r["close"] > 0:
                P["open"][i, j], P["high"][i, j], P["low"][i, j], P["close"][i, j] = r["open"], r["high"], r["low"], r["close"]
                P["qv"][i, j] = r.get("quote_volume", r["volume"] * r["close"])
    P["ts"], P["syms"] = ts, list(raw)
    return P


def split_relistings(raw, max_gap_days=7):
    """Ticker reutilizado / negociação suspensa (ex.: LUNA→Terra 2.0 em 2022-05-31, FTT 2022-11→2023-09, VEN→VET):
    um buraco > max_gap_days separa a série em activos distintos (SYM, SYM~2, ...) — sem isto o momentum "salta" entre
    o activo morto e o novo. Correcção de dados feita após a 1.ª execução (ver RELATORIO)."""
    out = {}
    for s, rows in raw.items():
        seg, k = [rows[0]], 1
        for a, b in zip(rows[:-1], rows[1:]):
            if b["start"] - a["start"] > max_gap_days * D:
                out[s if k == 1 else f"{s}~{k}"] = seg; seg, k = [], k + 1
            seg.append(b)
        out[s if k == 1 else f"{s}~{k}"] = seg
    return out


def shift(x, k):
    out = np.full_like(x, np.nan)
    if k < len(x): out[k:] = x[:-k] if k > 0 else x
    return out


def roll(x, n, fn):
    """Janela [t-n+1, t] (inclui t). NaN se faltar algum valor."""
    out = np.full_like(x, np.nan)
    if len(x) < n: return out
    w = np.lib.stride_tricks.sliding_window_view(x, n, axis=0)
    with np.errstate(all="ignore"): out[n - 1:] = fn(w, axis=-1)
    return out


def sma(c, n): return roll(c, n, np.mean)


def rvol(c, n, per_year=365):
    lr = np.log(c / shift(c, 1)); return roll(lr, n, np.std) * math.sqrt(per_year)


def universe(P, topn=TOPN, volwin=VOLWIN, min_hist=MIN_HIST):
    """U[t,a] = a está no top-N por volume dos `volwin` dias até t (inclusive; decisão no fecho de t) e tem ≥min_hist barras."""
    c = P["close"]; have = ~np.isnan(c)
    hist = np.cumsum(have, axis=0)
    qv = roll(np.nan_to_num(P["qv"]), volwin, np.sum)
    ok = have & (hist >= min_hist) & ~np.isnan(qv)
    score = np.where(ok, qv, -np.inf)
    U = np.zeros_like(ok)
    rank = np.argsort(-score, axis=1)[:, :topn]
    rows = np.arange(len(c))[:, None]
    U[rows, rank] = True
    return U & ok


# ---------------- motor (holdings reais; sinal em t → abertura t+1) ----------------
@njit(cache=True)
def simulate(O, Hh, L, C, W, reb, t0, t1, cost, stop_cost, stop, reentry, band_abs, band_rel):
    T, A = O.shape
    cash = 1.0; units = np.zeros(A); bpx = np.zeros(A); cin = np.zeros(A); cout = np.zeros(A)
    ent = np.full(A, -1); blocked = np.zeros(A, np.bool_); stop_t = np.full(A, -10 ** 9)
    eq = np.ones(t1 - t0); gross = np.zeros(t1 - t0); traded = 0.0
    maxn = (t1 - t0) * A + 1
    tr_ret = np.zeros(maxn); tr_in = np.zeros(maxn, np.int64); tr_out = np.zeros(maxn, np.int64); tr_why = np.zeros(maxn, np.int64); nt = 0
    for t in range(t0, t1):
        if t >= 1 and reb[t - 1] and (cash > 0 or units.sum() > 0):
            E = cash
            for a in range(A):
                if units[a] > 0: E += units[a] * O[t, a]
            for a in range(A):
                w = W[t - 1, a]
                if blocked[a] and ((not (w > 0)) or t - stop_t[a] >= reentry): blocked[a] = False
            for a in range(A):                                    # vendas primeiro
                if units[a] > 0:
                    w = W[t - 1, a]
                    tgt = 0.0 if (blocked[a] or not (w > 0)) else w
                    cur = units[a] * O[t, a] / E
                    if tgt == 0.0 or cur - tgt > max(band_abs, band_rel * cur):
                        q = units[a] - tgt * E / O[t, a]
                        if tgt == 0.0: q = units[a]
                        got = q * O[t, a] * (1 - cost); cash += got; cout[a] += got; units[a] -= q; traded += q * O[t, a]
                        if tgt == 0.0:
                            units[a] = 0.0; tr_ret[nt] = cout[a] / cin[a] - 1; tr_in[nt] = ent[a]; tr_out[nt] = t; tr_why[nt] = 0; nt += 1
                            cin[a] = 0.0; cout[a] = 0.0; bpx[a] = 0.0
            for a in range(A):                                    # compras
                w = W[t - 1, a]
                if blocked[a] or not (w >= 0.005) or not (O[t, a] > 0): continue
                cur = units[a] * O[t, a] / E
                if units[a] == 0.0 or w - cur > max(band_abs, band_rel * w):
                    q = (w * E - units[a] * O[t, a]) / O[t, a]
                    if q <= 0: continue
                    spend = q * O[t, a] * (1 + cost)
                    if spend > cash:
                        q *= cash / spend; spend = cash
                    if q <= 0: continue
                    if units[a] == 0.0: ent[a] = t; bpx[a] = O[t, a]
                    else: bpx[a] = (bpx[a] * units[a] + O[t, a] * q) / (units[a] + q)
                    cash -= spend; cin[a] += spend; units[a] += q; traded += q * O[t, a]
        Eo = cash
        for a in range(A):
            if units[a] > 0:
                if stop > 0:
                    sp = bpx[a] * (1 - stop)
                    if L[t, a] <= sp:
                        px = min(O[t, a], sp); got = units[a] * px * (1 - stop_cost); cash += got; cout[a] += got; traded += units[a] * px
                        units[a] = 0.0; tr_ret[nt] = cout[a] / cin[a] - 1; tr_in[nt] = ent[a]; tr_out[nt] = t; tr_why[nt] = 1; nt += 1
                        cin[a] = 0.0; cout[a] = 0.0; bpx[a] = 0.0; blocked[a] = True; stop_t[a] = t
                        continue
                if t + 1 >= T or not (O[t + 1, a] > 0) or t + 1 >= t1:     # deslistagem / fim da janela
                    px = C[t, a] if C[t, a] > 0 else O[t, a]
                    got = units[a] * px * (1 - stop_cost); cash += got; cout[a] += got; traded += units[a] * px
                    units[a] = 0.0; tr_ret[nt] = cout[a] / cin[a] - 1; tr_in[nt] = ent[a]; tr_out[nt] = t; tr_why[nt] = 2; nt += 1
                    cin[a] = 0.0; cout[a] = 0.0; bpx[a] = 0.0
        E = cash; g = 0.0
        for a in range(A):
            if units[a] > 0: E += units[a] * C[t, a]; g += units[a] * C[t, a]
        eq[t - t0] = E; gross[t - t0] = g / E if E > 0 else 0.0
    return eq, gross, traded, tr_ret[:nt], tr_in[:nt], tr_out[:nt], tr_why[:nt]


def run_sim(P, W, reb, t0, t1, cost=COST, stop_cost=None, stop=STOP, reentry=REENTRY_D):
    i0 = int(np.searchsorted(P["ts"], t0)); i1 = int(np.searchsorted(P["ts"], t1))
    sc = cost if stop_cost is None else stop_cost
    O = np.nan_to_num(P["open"]); Hh = np.nan_to_num(P["high"]); L = np.nan_to_num(P["low"]); C = np.nan_to_num(P["close"])
    out = simulate(O, Hh, L, C, np.nan_to_num(W).astype(np.float64), reb.astype(np.bool_), i0, i1, cost, sc, stop, reentry, BAND_ABS, BAND_REL)
    eq, gross, traded, tr, ti, to, tw = out
    return {"eq": eq, "gross": gross, "traded": traded, "tr_ret": tr, "tr_in": ti, "tr_out": to, "tr_why": tw, "i0": i0, "i1": i1}


def daily_returns(sim, ts, bar=D):
    eq = sim["eq"]
    if bar == D: return np.diff(np.r_[1.0, eq])  / np.r_[1.0, eq[:-1]]
    t = ts[sim["i0"]:sim["i1"]]; last = np.r_[(t[1:] // D) != (t[:-1] // D), True]   # fecho de cada dia UTC
    e = np.r_[1.0, eq[last]]; return e[1:] / e[:-1] - 1


def metrics(r, sim, ts, bar=D):
    n_tr = len(sim["tr_ret"]); tr = sim["tr_ret"]; yrs = len(r) / 365
    eq = np.cumprod(1 + r); pk = np.maximum.accumulate(np.r_[1.0, eq]); dd = float(((pk - np.r_[1.0, eq]) / pk).max())
    s = r.std(ddof=1)
    wins, losses = tr[tr > 0].sum(), -tr[tr <= 0].sum()
    return {"sharpe": float(r.mean() / s * math.sqrt(365)) if s > 0 else 0.0,
            "cagr": float(eq[-1] ** (1 / yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1.0, "total": float(eq[-1] - 1), "max_dd": dd,
            "trades": int(n_tr), "win_rate": float((tr > 0).mean()) if n_tr else 0.0,
            "profit_factor": float(wins / losses) if losses > 0 else None, "exp_r": float(tr.mean() / STOP) if n_tr else 0.0,
            "stops": int((sim["tr_why"] == 1).sum()), "exposure": float(sim["gross"].mean()),
            "turnover_yr": float(sim["traded"] / max(yrs, 1e-9) / max(1e-9, float(np.mean(sim["eq"])))), "days": len(r)}


# ---------------- estratégias: W[t,a] decidido no fecho de t (só dados ≤ t) ----------------
def weekly(ts): return ((ts // D) % 7) == 3              # decisão no fecho de domingo (UTC) → ordens na abertura de segunda 00:00 UTC


def every(ts, n): return ((ts // D) % n) == 0


def idx(P, names): return [P["syms"].index(s) for s in names if s in P["syms"]]


def s_tsmom(P, U, L, rebd):
    c = P["close"]; sig = (c / shift(c, L) - 1 > 0) & U
    return sig / TOPN, (weekly(P["ts"]) if rebd == 7 else np.ones(len(c), bool))


def s_xsmom(P, U, L, K, absf):
    c = P["close"]; m = c / shift(c, L) - 1; m = np.where(U & ~np.isnan(m), m, -np.inf)
    W = np.zeros_like(c); top = np.argsort(-m, axis=1)[:, :K]
    for k in range(K):
        a = top[:, k]; v = m[np.arange(len(c)), a]; ok = np.isfinite(v) & ((v > 0) if absf else True)
        W[np.arange(len(c))[ok], a[ok]] = 1.0 / K
    return W, weekly(P["ts"])


def s_trend(P, U, assets, n, vt):
    c = P["close"]; W = np.zeros_like(c); ix = idx(P, assets)
    for a in ix:
        on = c[:, a] > sma(c[:, a], n)
        w = np.ones(len(c)) / len(ix)
        if vt: w = w * np.minimum(1.0, 0.5 / rvol(c[:, a], 30))
        W[:, a] = np.where(on, np.nan_to_num(w), 0.0)
    return W, np.ones(len(c), bool)


def s_dualma(P, U, f, s):
    c = P["close"]; sig = (sma(c, f) > sma(c, s)) & U
    return sig / TOPN, np.ones(len(c), bool)


def s_breakout(P, U, N, M, vf):
    c, h, l = P["close"], P["high"], P["low"]
    hi = shift(roll(h, N, np.max), 1); lo = shift(roll(l, M, np.min), 1)
    comp = (rvol(c, 20) < rvol(c, 100)) if vf else np.ones_like(c, bool)
    entry = U & (c > hi) & comp; exitc = c < lo
    W = np.zeros_like(c); st = np.zeros(c.shape[1], bool)
    for t in range(len(c)):
        st = np.where(st, ~exitc[t] & ~np.isnan(c[t]), entry[t]); W[t] = st / TOPN
    return W, np.ones(len(c), bool)


def s_riskparity(P, U, which, L, rebd):
    c = P["close"]; rv = rvol(c, L)
    if which == "btceth":
        m = np.zeros_like(U); m[:, idx(P, ["BTC", "ETH"])] = True; m &= ~np.isnan(c)
    elif which == "top5": m = universe(P, topn=5)
    else: m = U
    iv = np.where(m & (rv > 0), 1.0 / rv, 0.0); s = iv.sum(axis=1, keepdims=True)
    return np.divide(iv, s, out=np.zeros_like(iv), where=s > 0), every(P["ts"], rebd)


def rsi(c, n=2):
    d = np.diff(c, prepend=np.nan, axis=0); up = np.clip(np.nan_to_num(d), 0, None); dn = np.clip(-np.nan_to_num(d), 0, None)
    au = np.zeros_like(c); ad = np.zeros_like(c); a = 1.0 / n
    for t in range(1, len(c)): au[t] = (1 - a) * au[t - 1] + a * up[t]; ad[t] = (1 - a) * ad[t - 1] + a * dn[t]
    out = 100 - 100 / (1 + np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0))
    out[np.isnan(c)] = np.nan; return out


def s_meanrev(P4, thr, trend, ex, max_hold=12):
    c = P4["close"]; r = rsi(c); tr = (c > sma(c, 300)) if trend else ~np.isnan(c)
    W = np.zeros_like(c); n = c.shape[1]; st = np.zeros(n, bool); age = np.zeros(n, int)
    for t in range(len(c)):
        new = ~st & (r[t] < thr) & tr[t]
        age = np.where(st, age + 1, 0)
        st = np.where(st, ~((r[t] > ex) | (age >= max_hold)) & ~np.isnan(c[t]), new)
        W[t] = st / n
    return W, np.ones(len(c), bool)


def s_bh_btc(P, U):
    W = np.zeros_like(P["close"]); W[:, idx(P, ["BTC"])] = 1.0; return W, np.ones(len(W), bool)


def s_bh_ew(P, U): return U / TOPN, every(P["ts"], 30)


FAMILIES = {
    "C1_tsmom": {"fn": "s_tsmom", "grid": {"L": [30, 60, 90, 120, 180], "rebd": [1, 7]}, "ordinal": ["L"]},
    "C2_xsmom_rotacao": {"fn": "s_xsmom", "grid": {"L": [30, 60, 90], "K": [1, 3, 5], "absf": [0, 1]}, "ordinal": ["L", "K"]},
    "C3_btc_eth_tendencia_vt": {"fn": "s_trend", "grid": {"assets": [["BTC"], ["BTC", "ETH"]], "n": [50, 100, 200], "vt": [0, 1]}, "ordinal": ["n"]},
    "C4_media_dupla": {"fn": "s_dualma", "grid": {"fs": [[10, 50], [20, 50], [20, 100], [50, 150], [50, 200]]}, "ordinal": ["fs"]},
    "C5_reversao_4h": {"fn": "s_meanrev", "grid": {"thr": [5, 10, 15], "trend": [0, 1], "ex": [50, 70]}, "ordinal": ["thr", "ex"], "bar": "4h"},
    "C6_rompimento_vol": {"fn": "s_breakout", "grid": {"N": [20, 55], "M": [10, 20], "vf": [0, 1]}, "ordinal": ["N", "M"]},
    "C7_paridade_risco": {"fn": "s_riskparity", "grid": {"which": ["btceth", "top5", "top10"], "L": [30, 90], "rebd": [7, 30]}, "ordinal": ["L", "rebd"]},
}
BASELINES = {"B0_buyhold_btc": "s_bh_btc", "B1_buyhold_top10_ew": "s_bh_ew"}


def variants():
    out = []
    for fam, f in FAMILIES.items():
        keys = list(f["grid"])
        for vals in itertools.product(*[f["grid"][k] for k in keys]):
            p = dict(zip(keys, vals))
            out.append({"fam": fam, "params": p, "id": fam + ":" + ",".join(f"{k}={'+'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in p.items())})
    return out


def weights(v, P, U, P4=None):
    p = v["params"]; fn = globals()[FAMILIES[v["fam"]]["fn"]]
    if v["fam"] == "C5_reversao_4h": return fn(P4, p["thr"], p["trend"], p["ex"])
    if v["fam"] == "C4_media_dupla": return fn(P, U, *p["fs"])
    return fn(P, U, *p.values())


def neighbours(v, allv):
    """Vizinhos = variantes da mesma família que diferem num ÚNICO parâmetro (ordinal: passo adjacente; categórico: qualquer)."""
    f = FAMILIES[v["fam"]]; out = []
    for u in allv:
        if u["fam"] != v["fam"] or u is v: continue
        diff = [k for k in f["grid"] if u["params"][k] != v["params"][k]]
        if len(diff) != 1: continue
        k = diff[0]
        if k in f["ordinal"]:
            g = f["grid"][k]
            if abs(g.index(u["params"][k]) - g.index(v["params"][k])) != 1: continue
        out.append(u)
    return out


# ---------------- estatística ----------------
def boot_p_mean(x, B=2000, block=10, seed=3):
    from desk.research.sweep import stationary_bootstrap_idx
    rng = np.random.default_rng(seed); m = x.mean(); c = x - m; T = len(x); cnt = 0
    for _ in range(B): cnt += c[stationary_bootstrap_idx(T, block, rng)].mean() >= m
    return cnt / B


def holm(ps):
    order = np.argsort(ps); m = len(ps); adj = np.zeros(m); run = 0.0
    for r, i in enumerate(order): run = max(run, (m - r) * ps[i]); adj[i] = min(1.0, run)
    return adj


def desk_caps(W, cap=0.125, maxpos=5):
    """Execução no desk: 1% risco/−8% stop ⇒ 12,5% por posição, ≤5 posições (máx. 62,5% investido)."""
    out = np.minimum(np.nan_to_num(W), cap)
    rk = np.argsort(np.argsort(-out, axis=1, kind="stable"), axis=1) < maxpos
    return np.where(rk & (out > 0), out, 0.0)


# ---------------- fases ----------------
SELECTION = ("IS 2018-01-01→2022-12-31: em cada família, campeão = maior Sharpe diário anualizado (custos base) entre variantes com "
             ">= 30 trades IS. Só os 7 campeões vão ao holdout 2023-01-01→2026-09-30, UMA vez. Holdout de todas as variantes é "
             "calculado só como diagnóstico (não muda a selecção).")
CRITERIA = ["V1 OOS Sharpe >= 0.5 e CAGR > 0 (custos base)",
            "V2 OOS Sharpe > 0 com custos 2x (0.38%/lado)",
            "V3 estabilidade IS: mediana do Sharpe dos vizinhos >= 50% do campeão E >= 50% da família com Sharpe IS > 0",
            "V4 DSR do campeão IS > 0.95 com N = todas as variantes deste estudo",
            "V5 White Reality Check IS (todas as variantes vs caixa, B=1000, bloco 10d) p < 0.05",
            "V6 bootstrap estacionário OOS (média diária > 0) p Holm (7 campeões) < 0.05",
            "V7 acrescenta valor ao buy&hold BTC: OOS Sharpe > Sharpe B&H BTC E max DD OOS < max DD B&H BTC",
            "SOBREVIVENTE = V1..V7; V1..V6 sem V7 = SÓ_BETA (não implanta); resto = REJEITADA. "
            "SOBREVIVENTE → spec + bot sombra em paper; implanta OFF salvo SOBREVIVENTE."]


def prereg_doc():
    vs = variants()
    return {"note": "escrito ANTES de qualquer cálculo no holdout (2023-01-01→2026-09-30); run recusa se o hash não bater",
            "data": {"daily": DIR_1D + " (data.binance.vision, USDT, inclui deslistados)", "h1": DIR_1H + " BTC,ETH,SOL → 4H"},
            "windows": {"is": [IS0, SPLIT], "oos": [SPLIT, OOS1]},
            "universe": f"top-{TOPN} por volume USDT {VOLWIN}d (point-in-time), >= {MIN_HIST} dias de histórico",
            "execution": "sinal no fecho t, ordem na abertura t+1; stop -8% do preço médio (taker); reentrada após sinal 0 ou 14 dias; "
                         f"banda de rebalance abs {BAND_ABS} / rel {BAND_REL}",
            "costs": {"base_per_side": COST, "x2_per_side": COST2X, "maker_sens_per_side": MAKER},
            "variants": [v["id"] for v in vs], "n_variants": len(vs), "prior_trials_project": PRIOR_TRIALS,
            "baselines": list(BASELINES), "selection": SELECTION, "criteria": CRITERIA}


def phase_prereg():
    doc = prereg_doc(); blob = json.dumps(doc, sort_keys=True); doc["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    json.dump(doc, open(PREREG, "w"), indent=1); print(doc["n_variants"], doc["sha256"]); return doc


def check_prereg(path=PREREG):
    doc = json.load(open(path)); h = doc.pop("sha256")
    if hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest() != h: raise SystemExit("pré-registo alterado: abortado")
    if doc != prereg_doc(): raise SystemExit("código diverge do pré-registo: abortado")
    return h


def load_4h():
    P1 = load_panel(DIR_1H, ["BTC", "ETH", "SOL"], bar=H)
    b = P1["ts"] // (4 * H); idx0 = np.flatnonzero(np.r_[True, b[1:] != b[:-1]]); ends = np.r_[idx0[1:], len(b)]
    with np.errstate(all="ignore"):
        P4 = {"ts": b[idx0] * 4 * H, "syms": P1["syms"], "open": P1["open"][idx0], "close": P1["close"][ends - 1],
              "high": np.fmax.reduceat(P1["high"], idx0, axis=0), "low": np.fmin.reduceat(P1["low"], idx0, axis=0),
              "qv": np.add.reduceat(np.nan_to_num(P1["qv"]), idx0, axis=0)}
    nn = np.add.reduceat((~np.isnan(P1["close"])).astype(int), idx0, axis=0)
    full = nn == 4                                                # barra 4H com hora em falta → NaN (por activo)
    for k in ("open", "close", "high", "low"): P4[k][~full] = np.nan
    return P4


def evaluate(v, P, U, P4, t0, t1, cost=COST, caps=False, stop=STOP):
    is4 = v.get("fam") == "C5_reversao_4h"; PP = P4 if is4 else P
    W, reb = weights(v, P, U, P4) if "fam" in v else globals()[v["fn"]](P, U)
    if caps: W = desk_caps(W)
    sim = run_sim(PP, W, reb, t0, t1, cost=cost, stop=stop, reentry=REENTRY_D * (6 if is4 else 1))
    r = daily_returns(sim, PP["ts"], 4 * H if is4 else D)
    return metrics(r, sim, PP["ts"]), r, sim


def by_year(r, t0):
    out = {}; days = t0 // D + np.arange(len(r))
    yrs = 1970 + ((days * D) // (365.2425 * D)).astype(int)
    for y in sorted(set(yrs.tolist())):
        x = r[yrs == y]; eq = np.cumprod(1 + x); pk = np.maximum.accumulate(np.r_[1.0, eq])
        out[str(y)] = {"ret": float(eq[-1] - 1), "sharpe": float(x.mean() / x.std(ddof=1) * math.sqrt(365)) if x.std() > 0 else 0.0,
                       "max_dd": float(((pk - np.r_[1.0, eq]) / pk).max())}
    return out


def phase_run():
    from desk.research.sweep import deflated_sharpe, reality_check
    h = check_prereg(); os.makedirs(STATE, exist_ok=True)
    P = load_panel(); U = universe(P); P4 = load_4h(); vs = variants()
    IS = {}; R_is = []
    for v in vs:
        m, r, _ = evaluate(v, P, U, P4, IS0, SPLIT); IS[v["id"]] = m; R_is.append(r)
    L = min(len(x) for x in R_is); M = np.array([x[:L] for x in R_is])
    base = {}
    for b, fn in BASELINES.items():
        bv = {"id": b, "fn": fn}
        base[b] = {"is": evaluate(bv, P, U, P4, IS0, SPLIT, stop=0.0)[0]}
        mo, ro, _ = evaluate(bv, P, U, P4, SPLIT, OOS1, stop=0.0); base[b]["oos"] = mo; base[b]["oos_by_year"] = by_year(ro, SPLIT)
    bh_is = evaluate({"id": "b", "fn": "s_bh_btc"}, P, U, P4, IS0, SPLIT, stop=0.0)[1][:L]
    sr_d = np.array([x.mean() / x.std(ddof=1) if x.std() > 0 else 0.0 for x in M])
    rc_cash = reality_check(M, B=1000); rc_bh = reality_check(M - bh_is, B=1000)
    champs = {}
    for fam in FAMILIES:
        fv = [v for v in vs if v["fam"] == fam]; el = [v for v in fv if IS[v["id"]]["trades"] >= 30] or fv
        ch = max(el, key=lambda v: IS[v["id"]]["sharpe"]); k = vs.index(ch)
        nb = neighbours(ch, vs); nbs = [IS[u["id"]]["sharpe"] for u in nb]
        dsr = deflated_sharpe(M[k], sr_d)
        # N acumulado do projecto: só muda N (variância dos SR deste estudo como proxy)
        import statistics
        nd = statistics.NormalDist(); em = 0.5772156649; N2 = len(vs) + PRIOR_TRIALS; v_sr = float(np.var(sr_d, ddof=1))
        sr0 = math.sqrt(v_sr) * ((1 - em) * nd.inv_cdf(1 - 1 / N2) + em * nd.inv_cdf(1 - 1 / (N2 * math.e)))
        z = (dsr["sr_daily"] - sr0) * math.sqrt(dsr["T"] - 1) / math.sqrt(max(1e-12, 1 - dsr["skew"] * dsr["sr_daily"] + (dsr["kurt"] - 1) / 4 * dsr["sr_daily"] ** 2))
        mo, ro, so = evaluate(ch, P, U, P4, SPLIT, OOS1)
        m2, _, _ = evaluate(ch, P, U, P4, SPLIT, OOS1, cost=COST2X)
        mm, _, _ = evaluate(ch, P, U, P4, SPLIT, OOS1, cost=MAKER)
        mc, _, _ = evaluate(ch, P, U, P4, SPLIT, OOS1, caps=True)
        mns, _, _ = evaluate(ch, P, U, P4, SPLIT, OOS1, stop=0.0)
        champs[fam] = {"id": ch["id"], "params": ch["params"], "is": IS[ch["id"]], "is_by_year": by_year(R_is[k], IS0),
                       "oos": mo, "oos_by_year": by_year(ro, SPLIT), "oos_2x": m2, "oos_maker": mm, "oos_desk_caps": mc, "oos_no_stop": mns,
                       "neigh": {"ids": [u["id"] for u in nb], "is_sharpe": nbs, "median": float(np.median(nbs)) if nbs else None},
                       "fam_frac_pos_is": float(np.mean([IS[v["id"]]["sharpe"] > 0 for v in fv])),
                       "dsr": dsr["dsr"], "dsr_project_N": nd.cdf(z), "N_project": N2,
                       "boot_p": boot_p_mean(ro), "_r": ro}
    ps = np.array([c["boot_p"] for c in champs.values()]); adj = holm(ps)
    bh = base["B0_buyhold_btc"]["oos"]
    for (fam, c), pa in zip(champs.items(), adj):
        c["boot_p_holm"] = float(pa); o = c["oos"]; ch_s = c["is"]["sharpe"]
        chk = {"V1": o["sharpe"] >= 0.5 and o["cagr"] > 0, "V2": c["oos_2x"]["sharpe"] > 0,
               "V3": (c["neigh"]["median"] is not None and ch_s > 0 and c["neigh"]["median"] >= 0.5 * ch_s) and c["fam_frac_pos_is"] >= 0.5,
               "V4": c["dsr"] > 0.95, "V5": rc_cash["p"] < 0.05, "V6": pa < 0.05,
               "V7": o["sharpe"] > bh["sharpe"] and o["max_dd"] < bh["max_dd"]}
        c["checks"] = {k: bool(v) for k, v in chk.items()}
        six = all(chk[k] for k in ("V1", "V2", "V3", "V4", "V5", "V6"))
        c["verdict"] = "SOBREVIVENTE" if six and chk["V7"] else ("SO_BETA" if six else "REJEITADA")
        del c["_r"]
    diag = {}
    for v in vs:
        m, _, _ = evaluate(v, P, U, P4, SPLIT, OOS1)
        diag[v["id"]] = {"is_sharpe": IS[v["id"]]["sharpe"], "oos_sharpe": m["sharpe"], "oos_cagr": m["cagr"], "oos_dd": m["max_dd"], "oos_trades": m["trades"]}
    rep = {"prereg_sha256": h, "n_variants": len(vs), "n_project_cum": len(vs) + PRIOR_TRIALS, "rc_is_vs_cash": rc_cash, "rc_is_vs_bh_btc": rc_bh,
           "baselines": base, "champions": champs, "is_all": IS, "diagnostic_oos_all": diag,
           "frac_is_sharpe_pos": float(np.mean([IS[v["id"]]["sharpe"] > 0 for v in vs])),
           "frac_oos_sharpe_pos_diag": float(np.mean([d["oos_sharpe"] > 0 for d in diag.values()])),
           "universe_members_oos": sorted({P["syms"][a] for a in np.flatnonzero(U[np.searchsorted(P["ts"], SPLIT):np.searchsorted(P["ts"], OOS1)].any(axis=0))}),
           "universe_members_is": sorted({P["syms"][a] for a in np.flatnonzero(U[np.searchsorted(P["ts"], IS0):np.searchsorted(P["ts"], SPLIT)].any(axis=0))})}
    json.dump(rep, open(f"{STATE}/estudo_report.json", "w"), indent=1, default=float)
    for fam, c in champs.items():
        print(f"{fam:26s} {c['id'][len(fam)+1:]:28s} IS S={c['is']['sharpe']:+.2f} OOS S={c['oos']['sharpe']:+.2f} 2x={c['oos_2x']['sharpe']:+.2f} "
              f"DD={c['oos']['max_dd']:.0%} n={c['oos']['trades']} dsr={c['dsr']:.2f} p={c['boot_p_holm']:.3f} {c['checks']} {c['verdict']}")
    print("RC cash", rc_cash, "RC bh", rc_bh); print("BH", {k: (v['is']['sharpe'], v['oos']['sharpe'], v['oos']['max_dd']) for k, v in base.items()})
    return rep


def phase_posthoc():
    """DIAGNÓSTICO pós-holdout (não muda veredictos): DSR sem a família C5 (SR muito negativos inflacionam a variância)
    e verificação de venue do campeão C3 nas velas 1D PÚBLICAS da Revolut X (BTC/ETH, ~1000 dias)."""
    from desk.research.sweep import deflated_sharpe
    from desk.research.regime import get, RX
    rep = json.load(open(f"{STATE}/estudo_report.json")); P = load_panel(); U = universe(P); P4 = load_4h(); vs = variants()
    R = {v["id"]: evaluate(v, P, U, P4, IS0, SPLIT)[1] for v in vs}; L = min(len(x) for x in R.values())
    keep = [v["id"] for v in vs if v["fam"] != "C5_reversao_4h"]
    srs = np.array([R[k][:L].mean() / R[k][:L].std(ddof=1) for k in keep])
    out = {"dsr_excl_C5": {fam: deflated_sharpe(R[c["id"]][:L], srs)["dsr"] for fam, c in rep["champions"].items() if fam != "C5_reversao_4h"},
           "dsr_family_only": {}}
    for fam, c in rep["champions"].items():
        ids = [v["id"] for v in vs if v["fam"] == fam]; s2 = np.array([R[k][:L].mean() / R[k][:L].std(ddof=1) for k in ids])
        out["dsr_family_only"][fam] = deflated_sharpe(R[c["id"]][:L], s2)["dsr"]
    rows = {}
    for s in ("BTC", "ETH"):
        j = get(f"{RX}/public/candles/{s}-USD", {"interval": 1440})
        if not j or not j.get("data"): out["venue_error"] = f"candles {s}"; break
        now = int(__import__("time").time() * 1000)
        rows[s] = [{"start": (int(r["start"]) + 12 * H) // D * D, **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}} for r in j["data"] if int(r["start"]) + D <= now]
    if len(rows) == 2:
        d = os.path.join(STATE, "revx_1d"); os.makedirs(d, exist_ok=True)
        for s, r in rows.items(): json.dump(sorted(r, key=lambda x: x["start"]), open(os.path.join(d, f"{s}.json"), "w"))
        PR = load_panel(d, ["BTC", "ETH"], bar=D)
        t0 = int(PR["ts"][120]); t1 = int(PR["ts"][-1]) + D; UR = ~np.isnan(PR["close"])
        ch = next(v for v in vs if v["id"] == rep["champions"]["C3_btc_eth_tendencia_vt"]["id"])
        m, _, _ = evaluate(ch, PR, UR, None, t0, t1); b, _, _ = evaluate({"id": "b", "fn": "s_bh_btc"}, PR, UR, None, t0, t1, stop=0.0)
        mc, _, _ = evaluate(ch, PR, UR, None, t0, t1, caps=True)
        out["venue_revx_c3"] = {"from_ms": t0, "to_ms": t1, "c3": m, "c3_desk_caps": mc, "bh_btc": b}
    json.dump(out, open(f"{STATE}/posthoc.json", "w"), indent=1, default=float); print(json.dumps(out, indent=1, default=float)[:3000])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=["prereg", "run", "regime", "posthoc"]); a = ap.parse_args()
    if a.phase == "prereg": phase_prereg()
    elif a.phase == "run": phase_run()
    elif a.phase == "posthoc": phase_posthoc()
    else:
        from desk.research.regime import main as rm; rm()


if __name__ == "__main__":
    main()
