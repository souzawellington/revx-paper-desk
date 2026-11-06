"""Teste histórico PRÉ-REGISTADO das estratégias de scalping intradiário do manual (só COMPRA: Revolut X é spot, sem short).
Disciplina (igual a estudo.py / exitgrid.py):
  * dados PÚBLICOS data.binance.vision 1m (USDT como proxy dos pares USD da Revolut X) BTC ETH SOL XRP DOGE ADA, 2024-09→2026-09;
    5m = reamostragem do 1m; verificação de buracos / barras inválidas (barra inválida ou em falta bloqueia entradas 30 barras);
  * divisão CRONOLÓGICA: DEV 2024-10-01→2026-02-01 = treino (primeiros 90%) + validação (últimos 10%, 2025-12-14→);
    HOLDOUT intocado 2026-02-01→2026-10-01, avaliado UMA vez só para os campeões; walk-forward 90d→30d dentro do DEV;
  * sinal no FECHO da barra t → taker: compra na abertura t+1; maker: limite = fecho t, válida 3 barras, só enche se o preço
    passar ATRAVÉS do limite (low < limite), ordens não cheias contadas; stop SEMPRE taker; stop e alvo na mesma barra → stop;
  * custos: taker 0,09%/lado + 2 bp slippage; maker 0% (entrada e alvo), saídas por stop/sinal/tempo taker; stress 4 bp;
  * 1% de risco por trade sobre $65, conta: −3% no dia pausa até ao dia seguinte, −5% do topo pausa até ao dia seguinte;
  * grelha + regra de selecção + critérios pré-registados em desk/research/prereg_scalp.json (SHA-256) ANTES de olhar resultados;
    `run` recusa se o hash não bater ou se o código divergir; DSR (N deste estudo + N acumulado do projecto) + White Reality Check.
python -m desk.research.scalp quality | prereg | run
Nada aqui toca execution_mode, live/, chaves, bots ou limiares do auditor.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json, math, os, statistics
import numpy as np

try:
    from numba import njit
except Exception:                       # venv do desk/testes: Python puro, mesmos resultados
    def njit(*a, **k):
        if a and callable(a[0]): return a[0]
        return lambda f: f

M1, D = 60_000, 86_400_000
DIR = "data_ext/binance_vision/1m"
STATE = "desk/state/scalp"
PREREG = "desk/research/prereg_scalp.json"
SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"]
DATA0 = 1725148800000                    # 2024-09-01 (aquecimento dos indicadores)
DEV0, VAL0, OOS0, OOS1 = 1727740800000, 1765670400000, 1769904000000, 1790812800000   # 2024-10-01 | 2025-12-14 | 2026-02-01 | 2026-10-01
TAKER, MAKER_FEE, SLIP, SLIP_STRESS = 0.0009, 0.0, 0.0002, 0.0004
LIMIT_VALID, BLOCK_AFTER_BAD = 3, 30
RISK, POS_CAP, MAX_OPEN, START_USD = 0.01, 0.25, 4, 65.0
DAY_HALT, PEAK_BREAKER = 0.03, 0.05
PRIOR_TRIALS = 7335                      # variantes testadas antes no projecto (exitgrid 7200 + sweep/presample/specs 58 + estudo 77)
MIN_TRAIN_TRADES, MIN_OOS_TRADES, WF_TRAIN_D, WF_TEST_D, WF_MIN = 300, 100, 90, 30, 30
ATR_TABLE = [(0.0015, 1.0, 1.5), (0.0035, 1.5, 2.0), (math.inf, 2.0, 3.0)]   # ATR% < 0,15% | 0,15–0,35% | > 0,35%


# ---------------- dados ----------------
def load_1m(sym, d=DIR):
    z = np.load(os.path.join(d, f"{sym}.npz")); return {k: z[k] for k in ("ts", "o", "h", "l", "c", "v")}


def to_grid(raw, t0=DATA0, t1=OOS1, bar=M1):
    """Grelha completa de minutos. Em falta / inválida → O=H=L=C=fecho anterior, v=0, bad=True."""
    n = (t1 - t0) // bar; ts = t0 + np.arange(n, dtype=np.int64) * bar
    o, h, l, c, v = (np.full(n, np.nan) for _ in range(5))
    i = (raw["ts"] - t0) // bar; ok = (i >= 0) & (i < n) & ((raw["ts"] - t0) % bar == 0)
    for a, k in ((o, "o"), (h, "h"), (l, "l"), (c, "c"), (v, "v")): a[i[ok]] = raw[k][ok]
    with np.errstate(invalid="ignore"):
        valid = (~np.isnan(c)) & (o > 0) & (l > 0) & (h >= np.maximum(o, c) - 1e-12) & (l <= np.minimum(o, c) + 1e-12) & (v >= 0)
    bad = ~valid
    lc = np.where(valid, c, np.nan); idx = np.where(valid, np.arange(n), 0); np.maximum.accumulate(idx, out=idx)
    fill = lc[idx]; first = np.argmax(valid) if valid.any() else n
    for a in (o, h, l, c): a[bad] = fill[bad]
    v[bad] = 0.0
    for a in (o, h, l, c): a[:first] = fill[first] if first < n else np.nan
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c, "v": v, "bad": bad}


def resample(g, k=5):
    n = len(g["ts"]) // k * k; R = lambda x: x[:n].reshape(-1, k)
    return {"ts": g["ts"][:n:k], "o": R(g["o"])[:, 0], "h": R(g["h"]).max(1), "l": R(g["l"]).min(1), "c": R(g["c"])[:, -1],
            "v": R(g["v"]).sum(1), "bad": R(g["bad"]).any(1)}


def quality(raw, g):
    lr = np.abs(np.diff(np.log(g["c"])))
    return {"rows_file": int(len(raw["ts"])), "grid_bars": int(len(g["ts"])), "missing_or_invalid": int(g["bad"].sum()),
            "duplicates": int(len(raw["ts"]) - len(np.unique(raw["ts"]))), "zero_volume_bars": int(((g["v"] == 0) & ~g["bad"]).sum()),
            "abs_1m_move_gt_5pct": int((lr > 0.05).sum()), "abs_1m_move_gt_20pct": int((lr > 0.20).sum()),
            "max_abs_1m_logret": float(lr.max())}


# ---------------- indicadores (só dados ≤ t) ----------------
@njit(cache=True)
def ema(x, n):
    out = np.empty_like(x); a = 2.0 / (n + 1); out[0] = x[0]
    for t in range(1, len(x)): out[t] = a * x[t] + (1 - a) * out[t - 1]
    return out


@njit(cache=True)
def wilder_rsi(c, n):
    out = np.full(len(c), np.nan); au = 0.0; ad = 0.0
    for t in range(1, len(c)):
        d = c[t] - c[t - 1]; up = d if d > 0 else 0.0; dn = -d if d < 0 else 0.0
        if t <= n:
            au += up / n; ad += dn / n
        else:
            au = (au * (n - 1) + up) / n; ad = (ad * (n - 1) + dn) / n
        if t >= n: out[t] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    return out


@njit(cache=True)
def wilder_atr(h, l, c, n):
    out = np.full(len(c), np.nan); a = 0.0
    for t in range(1, len(c)):
        tr = max(h[t] - l[t], abs(h[t] - c[t - 1]), abs(l[t] - c[t - 1]))
        if t <= n: a += tr / n
        else: a = (a * (n - 1) + tr) / n
        if t >= n: out[t] = a
    return out


@njit(cache=True)
def roll_mean_std(x, n):
    m = np.full(len(x), np.nan); s = np.full(len(x), np.nan)
    for t in range(n - 1, len(x)):
        w = x[t - n + 1:t + 1]; mu = w.mean(); m[t] = mu; s[t] = math.sqrt(((w - mu) ** 2).mean())
    return m, s


@njit(cache=True)
def prev_max(x, n):
    """max(x[t-n..t-1]) — exclui a barra t."""
    out = np.full(len(x), np.nan)
    for t in range(n, len(x)): out[t] = x[t - n:t].max()
    return out


@njit(cache=True)
def prev_mean(x, n):
    out = np.full(len(x), np.nan)
    for t in range(n, len(x)): out[t] = x[t - n:t].mean()
    return out


@njit(cache=True)
def pct_rank(x, n):
    """Fracção das n barras anteriores (t-n..t-1) com valor <= x[t]."""
    out = np.full(len(x), np.nan)
    for t in range(n, len(x)):
        if np.isnan(x[t]): continue
        k = 0; m = 0
        for j in range(t - n, t):
            if not np.isnan(x[j]):
                m += 1
                if x[j] <= x[t]: k += 1
        if m > 0: out[t] = k / m
    return out


@njit(cache=True)
def recent_bad(bad, n):
    out = np.zeros(len(bad), np.bool_); last = -10 ** 9
    for t in range(len(bad)):
        if bad[t]: last = t
        out[t] = t - last < n
    return out


def atr_regime(atr, c):
    p = atr / c; slm = np.where(p < ATR_TABLE[0][0], 1.0, np.where(p <= ATR_TABLE[1][0], 1.5, 2.0))
    tpm = np.where(p < ATR_TABLE[0][0], 1.5, np.where(p <= ATR_TABLE[1][0], 2.0, 3.0))
    return slm * atr, tpm * atr


def features(g):
    c, h, l, v = g["c"], g["h"], g["l"], g["v"]; f = {"c": c}
    f["atr"] = wilder_atr(h, l, c, 14); f["sld"], f["tpd"] = atr_regime(f["atr"], c)
    f["rsi"] = wilder_rsi(c, 14); f["mid"], sd = roll_mean_std(c, 20)
    for k in (2.0, 2.5, 3.0): f[f"lo{k}"] = f["mid"] - k * sd
    f["e9"], f["e21"] = ema(c, 9), ema(c, 21)
    with np.errstate(invalid="ignore", divide="ignore"): f["width"] = 4.0 * sd / f["mid"]
    f["wpct"] = pct_rank(f["width"], 240); f["hh20"] = prev_max(h, 20); f["vavg20"] = prev_mean(v, 20)
    f["block"] = recent_bad(g["bad"], BLOCK_AFTER_BAD) | np.isnan(f["atr"]) | np.isnan(f["mid"]) | (f["atr"] <= 0)
    return f


# ---------------- estratégias: sinal no fecho de t (só dados ≤ t) ----------------
def sig_bbrsi(g, f, k, rsi_thr):
    lo = f[f"lo{k}"]
    with np.errstate(invalid="ignore"):
        s = g["l"] <= lo
        if rsi_thr is not None: s &= f["rsi"] < rsi_thr
    return s, np.full(len(s), np.nan), f["mid"], np.zeros(len(s), bool)          # alvo dinâmico = banda do meio


def sig_ema(g, f, exit_mode):
    e9, e21, l, c = f["e9"], f["e21"], g["l"], g["c"]
    with np.errstate(invalid="ignore"):
        up = (e9 > e21) & (e9 > np.r_[np.nan, e9[:-1]]) & (e21 > np.r_[np.nan, e21[:-1]])
        touch = (l <= e9) & (c > e21); first = touch & ~np.r_[False, touch[:-1]]
        inval = c < e21
    tp = f["tpd"] if exit_mode == "atr_tp" else np.full(len(c), np.nan)
    return up & first, tp, None, inval


def sig_squeeze(g, f, pct, kvol):
    with np.errstate(invalid="ignore"):
        sq = f["wpct"] <= pct / 100.0; sq_prev = np.zeros(len(sq), bool)
        for j in range(1, 6): sq_prev |= np.r_[np.zeros(j, bool), sq[:-j]]
        s = sq_prev & (g["c"] > f["hh20"]) & (g["v"] > kvol * f["vavg20"]) & (f["width"] > np.r_[np.nan, f["width"][:-1]])
    return s, f["tpd"], None, np.zeros(len(s), bool)


FAMILIES = {
    "S1_bb_rsi_reversao": {"grid": {"tf": [1, 5], "bb": ["2.0/rsi20", "2.0/rsi25", "2.5/rsi20", "2.5/rsi25", "3.0/puro"], "tstop": [5, 15],
                                    "exec": ["taker", "maker"]}},
    "S2_ema9_21_recuo": {"grid": {"tf": [1, 5], "exit": ["atr_tp", "ema_only"], "tstop": [15, 45], "exec": ["taker", "maker"]}},
    "S3_squeeze_volume": {"grid": {"tf": [1, 5], "pct": [10, 20], "kvol": [1.5, 2.5], "tstop": [15, 45], "exec": ["taker", "maker"]}},
}


def variants():
    out = []
    for fam, fd in FAMILIES.items():
        keys = list(fd["grid"])
        for vals in itertools.product(*[fd["grid"][k] for k in keys]):
            p = dict(zip(keys, vals)); out.append({"fam": fam, "params": p, "id": fam + ":" + ",".join(f"{k}={v}" for k, v in p.items())})
    return out


def signals(v, g, f):
    p = v["params"]
    if v["fam"] == "S1_bb_rsi_reversao":
        k, r = p["bb"].split("/"); return sig_bbrsi(g, f, float(k), None if r == "puro" else float(r[3:]))
    if v["fam"] == "S2_ema9_21_recuo": return sig_ema(g, f, p["exit"])
    return sig_squeeze(g, f, p["pct"], p["kvol"])


# ---------------- motor (1 posição por par; long only) ----------------
@njit(cache=True)
def simulate(o, h, l, c, sig, lim, sld, tpd, tpdyn, use_dyn, inval, tstop, maker, slip, fee_t, fee_m, valid, block, i0, i1, cap):
    """why: 0 alvo, 1 stop, 2 invalidação (fecho < EMA21), 3 tempo, 4 fim da janela. Devolve trades + nº de sinais e limites falhados."""
    e_i = np.zeros(cap, np.int64); x_i = np.zeros(cap, np.int64); e_px = np.zeros(cap); x_px = np.zeros(cap); s_px = np.zeros(cap)
    R = np.zeros(cap); ret = np.zeros(cap); why = np.zeros(cap, np.int64); nt = 0
    state = 0; s_bar = -1; lim_px = 0.0; sl_d = 0.0; tp_d = np.nan
    ent = 0.0; sl = 0.0; tp = np.nan; fin = 0.0; ebar = 0; pend_exit = False; nsig = 0; nmiss = 0; px = 0.0; fo = 0.0; w = 0
    for t in range(i0, i1):
        if state == 2 and pend_exit:                                   # saída a mercado na abertura (taker)
            px = o[t] * (1 - slip); pnl = px * (1 - fee_t) - ent * (1 + fin)
            e_i[nt] = ebar; x_i[nt] = t; e_px[nt] = ent; x_px[nt] = px; s_px[nt] = sl; R[nt] = pnl / (ent - sl); ret[nt] = pnl / (ent * (1 + fin))
            why[nt] = 3 if (t - ebar) >= tstop else 2; nt += 1; state = 0; pend_exit = False
        if state == 1:                                                 # limite maker pendente
            if l[t] < lim_px:
                state = 2; ent = lim_px; fin = fee_m; ebar = t; sl = ent - sl_d; tp = ent + tp_d
                if l[t] <= sl:                                         # encheu e furou o stop na mesma barra
                    px = min(o[t], sl) * (1 - slip)
                    pnl = px * (1 - fee_t) - ent * (1 + fin)
                    e_i[nt] = ebar; x_i[nt] = t; e_px[nt] = ent; x_px[nt] = px; s_px[nt] = sl; R[nt] = pnl / (ent - sl); ret[nt] = pnl / (ent * (1 + fin))
                    why[nt] = 1; nt += 1; state = 0
                    continue
                if t == i1 - 1 or inval[t] or (t - ebar + 1) >= tstop:
                    if t + 1 < i1: pend_exit = True
                continue
            elif t - s_bar >= valid:
                state = 0; nmiss += 1
        if state == 2:
            tpl = tpdyn[t - 1] if use_dyn else tp
            done = False
            if o[t] <= sl:
                px = o[t] * (1 - slip); w = 1; done = True; fo = fee_t
            elif l[t] <= sl:
                px = sl * (1 - slip); w = 1; done = True; fo = fee_t
            elif (not np.isnan(tpl)) and ((h[t] > tpl) if maker else (h[t] >= tpl)):
                if maker:
                    px = tpl; fo = fee_m
                else:
                    px = max(tpl, o[t]) * (1 - slip); fo = fee_t
                w = 0; done = True
            if done:
                pnl = px * (1 - fo) - ent * (1 + fin)
                e_i[nt] = ebar; x_i[nt] = t; e_px[nt] = ent; x_px[nt] = px; s_px[nt] = sl; R[nt] = pnl / (ent - sl); ret[nt] = pnl / (ent * (1 + fin))
                why[nt] = w; nt += 1; state = 0
            elif t == i1 - 1:
                px = c[t] * (1 - slip); pnl = px * (1 - fee_t) - ent * (1 + fin)
                e_i[nt] = ebar; x_i[nt] = t; e_px[nt] = ent; x_px[nt] = px; s_px[nt] = sl; R[nt] = pnl / (ent - sl); ret[nt] = pnl / (ent * (1 + fin))
                why[nt] = 4; nt += 1; state = 0
            elif inval[t] or (t - ebar + 1) >= tstop:
                pend_exit = True
            continue
        if state == 0 and sig[t] and not block[t] and t + 1 < i1 and sld[t] > 0:
            nsig += 1
            if maker:
                state = 1; s_bar = t; lim_px = lim[t]; sl_d = sld[t]; tp_d = tpd[t]
            else:
                ent = o[t + 1] * (1 + slip); fin = fee_t; ebar = t + 1; sl = ent - sld[t]; tp = ent + tpd[t]; state = 2
    if state == 2:                                                     # fecho forçado no fim da janela
        t = i1 - 1; px = c[t] * (1 - slip); pnl = px * (1 - fee_t) - ent * (1 + fin)
        e_i[nt] = ebar; x_i[nt] = t; e_px[nt] = ent; x_px[nt] = px; s_px[nt] = sl; R[nt] = pnl / (ent - sl); ret[nt] = pnl / (ent * (1 + fin))
        why[nt] = 4; nt += 1
    return e_i[:nt], x_i[:nt], e_px[:nt], x_px[:nt], s_px[:nt], R[:nt], ret[:nt], why[:nt], nsig, nmiss


def run_variant(v, g, f, t0, t1, slip=SLIP, fee=TAKER):
    p = v["params"]; sig, tpd, dyn, inval = signals(v, g, f); maker = p["exec"] == "maker"
    i0 = int(np.searchsorted(g["ts"], t0)); i1 = int(np.searchsorted(g["ts"], t1))
    sig = np.nan_to_num(sig).astype(np.bool_); cap = int(sig[i0:i1].sum()) + 2
    out = simulate(g["o"], g["h"], g["l"], g["c"], sig, g["c"], np.nan_to_num(f["sld"]), tpd.astype(np.float64),
                   (dyn if dyn is not None else np.full(len(sig), np.nan)).astype(np.float64), dyn is not None,
                   np.nan_to_num(inval).astype(np.bool_), int(p["tstop"]), maker, slip, fee, MAKER_FEE, LIMIT_VALID,
                   f["block"].astype(np.bool_), i0, i1, cap)
    ei, xi, ep, xp, sp, R, ret, why, nsig, nmiss = out
    return {"e_ts": g["ts"][ei], "x_ts": g["ts"][xi] + (g["ts"][1] - g["ts"][0]), "R": R, "ret": ret, "why": why,
            "stopdist": (ep - sp) / ep, "hold_min": (xi - ei + 1) * (g["ts"][1] - g["ts"][0]) / M1, "nsig": int(nsig), "nmiss": int(nmiss)}


def merge(trs):
    keys = ["e_ts", "x_ts", "R", "ret", "why", "stopdist", "hold_min"]
    out = {k: np.concatenate([t[k] for t in trs]) if trs else np.zeros(0) for k in keys}
    out["pair"] = np.concatenate([np.full(len(t["R"]), j) for j, t in enumerate(trs)]) if trs else np.zeros(0, int)
    o = np.argsort(out["e_ts"], kind="stable"); out = {k: v[o] for k, v in out.items()}
    out["nsig"] = sum(t["nsig"] for t in trs); out["nmiss"] = sum(t["nmiss"] for t in trs); return out


def subset(T, t0, t1):
    m = (T["e_ts"] >= t0) & (T["e_ts"] < t1); out = {k: (v[m] if isinstance(v, np.ndarray) else v) for k, v in T.items()}; return out


# ---------------- métricas ----------------
def daily_series(T, t0, t1):
    """Retorno diário da conta (sem limites de conta): soma de w×ret no dia de saída, w = min(1%/dist. stop, 25%)."""
    nd = int((t1 - t0) // D); r = np.zeros(nd)
    if len(T["R"]):
        w = np.minimum(RISK / np.maximum(T["stopdist"], 1e-9), POS_CAP); d = np.clip((T["x_ts"] - 1 - t0) // D, 0, nd - 1)
        np.add.at(r, d, w * T["ret"])
    return r


def max_dd(r):
    eq = np.cumprod(1 + r); pk = np.maximum.accumulate(np.r_[1.0, eq]); return float(((pk - np.r_[1.0, eq]) / pk).max())


def sharpe(r): s = r.std(ddof=1) if len(r) > 1 else 0.0; return float(r.mean() / s * math.sqrt(365)) if s > 0 else 0.0


def sortino(r):
    dn = r[r < 0]; s = math.sqrt((dn ** 2).sum() / len(r)) if len(r) and len(dn) else 0.0
    return float(r.mean() / s * math.sqrt(365)) if s > 0 else 0.0


def stats(T, t0, t1):
    R = T["R"]; n = len(R); days = (t1 - t0) / D; r = daily_series(T, t0, t1); w, ls = R[R > 0].sum(), -R[R <= 0].sum()
    return {"trades": n, "trades_per_day": n / days, "days_to_40": (40 / (n / days)) if n else None,
            "exp_r": float(R.mean()) if n else 0.0, "median_r": float(np.median(R)) if n else 0.0, "win_rate": float((R > 0).mean()) if n else 0.0,
            "profit_factor_r": float(w / ls) if ls > 0 else None, "avg_ret_notional": float(T["ret"].mean()) if n else 0.0,
            "avg_stop_dist": float(T["stopdist"].mean()) if n else 0.0, "avg_hold_min": float(T["hold_min"].mean()) if n else 0.0,
            "exits": {k: int((T["why"] == i).sum()) for i, k in enumerate(["alvo", "stop", "invalidacao", "tempo", "fim"])},
            "signals": int(T["nsig"]), "missed_limits": int(T["nmiss"]), "fill_rate": (1 - T["nmiss"] / T["nsig"]) if T["nsig"] else None,
            "sharpe": sharpe(r), "sortino": sortino(r), "max_dd": max_dd(r), "total_ret": float(np.prod(1 + r) - 1), "days": days}


def account(T, start=START_USD):
    """Conta de $65: 1% de risco, posição ≤ 25% do saldo, ≤4 abertas, sem alavancagem; −3% no dia → pausa até 00:00 UTC;
    −5% do topo → pausa até 00:00 UTC (o topo é reposto ao saldo actual). Marcação ao custo (só realizado)."""
    eq = start; peak = start; day = None; day_eq = start; paused_until = -1; open_ = []; dd = 0.0
    n = 0; skip_halt = 0; skip_cash = 0; halts = 0; breaks = 0; first_break = None
    order = np.argsort(T["e_ts"], kind="stable")
    def close_until(ts):
        nonlocal eq, peak, dd, paused_until, halts, breaks, first_break, day, day_eq
        open_.sort()
        while open_ and open_[0][0] <= ts:
            xt, notional, ret = open_.pop(0); dday = xt // D
            if day != dday: day, day_eq = dday, eq
            eq += notional * ret; peak = max(peak, eq); dd = max(dd, (peak - eq) / peak)
            if (eq - day_eq) / day_eq <= -DAY_HALT and paused_until < (dday + 1) * D: paused_until = (dday + 1) * D; halts += 1
            if (peak - eq) / peak >= PEAK_BREAKER:
                breaks += 1; first_break = first_break or int(xt); paused_until = max(paused_until, (dday + 1) * D); peak = eq
    for i in order:
        te = int(T["e_ts"][i]); close_until(te)
        dday = te // D
        if day != dday: day, day_eq = dday, eq
        if te < paused_until: skip_halt += 1; continue
        used = sum(x[1] for x in open_)
        if len(open_) >= MAX_OPEN: skip_cash += 1; continue
        notional = min(RISK * eq / max(T["stopdist"][i], 1e-9), POS_CAP * eq, eq - used)
        if notional <= 0.01: skip_cash += 1; continue
        open_.append((int(T["x_ts"][i]), notional, float(T["ret"][i]))); n += 1
    close_until(2 ** 62)
    return {"start_usd": start, "end_usd": eq, "ret": eq / start - 1, "max_dd_realized": dd, "trades_taken": n, "skipped_paused": skip_halt,
            "skipped_no_cash_or_slots": skip_cash, "day_halts": halts, "peak_breaker_trips": breaks, "first_breaker_ts": first_break}


def boot_p_mean(x, B=2000, block=5, seed=3):
    from desk.research.sweep import stationary_bootstrap_idx
    rng = np.random.default_rng(seed); m = x.mean(); c = x - m; cnt = 0
    for _ in range(B): cnt += c[stationary_bootstrap_idx(len(x), block, rng)].mean() >= m
    return cnt / B


def holm(ps):
    order = np.argsort(ps); m = len(ps); adj = np.zeros(m); run = 0.0
    for r, i in enumerate(order): run = max(run, (m - r) * ps[i]); adj[i] = min(1.0, run)
    return adj


def dsr_n(x, all_sr, N):
    """DSR (Bailey & López de Prado) com N ensaios declarado; variância dos SR = a deste estudo."""
    nd = statistics.NormalDist(); T = len(x); s = x.std(ddof=1)
    if s == 0 or T < 3: return 0.0
    sr = x.mean() / s; g3 = float(((x - x.mean()) ** 3).mean() / x.std() ** 3); g4 = float(((x - x.mean()) ** 4).mean() / x.std() ** 4)
    em = 0.5772156649; v = float(np.var(all_sr, ddof=1))
    sr0 = math.sqrt(v) * ((1 - em) * nd.inv_cdf(1 - 1 / N) + em * nd.inv_cdf(1 - 1 / (N * math.e)))
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(nd.cdf(z))


def walk_forward(trades_by_vid, t0=DEV0, t1=OOS0):
    """Dentro do DEV: a cada 30 dias escolhe a variante (mesma família e execução) com maior R médio nos 90 dias anteriores
    (>= 30 trades) e usa-a nos 30 dias seguintes. Devolve os R concatenados das janelas de teste."""
    out, picks = [], []; s = t0 + WF_TRAIN_D * D
    while s + WF_TEST_D * D <= t1:
        best, bv = None, -math.inf
        for vid, T in trades_by_vid.items():
            m = (T["e_ts"] >= s - WF_TRAIN_D * D) & (T["e_ts"] < s)
            if m.sum() >= WF_MIN and T["R"][m].mean() > bv: best, bv = vid, T["R"][m].mean()
        if best:
            T = trades_by_vid[best]; m = (T["e_ts"] >= s) & (T["e_ts"] < s + WF_TEST_D * D); out.append(T["R"][m]); picks.append(best)
        s += WF_TEST_D * D
    x = np.concatenate(out) if out else np.zeros(0)
    return {"exp_r": float(x.mean()) if len(x) else 0.0, "trades": int(len(x)), "folds": len(out), "picks": picks}


# ---------------- pré-registo ----------------
SELECTION = (f"TREINO 2024-10-01→2025-12-14 (90% do DEV): em cada (família × execução taker/maker) o campeão = maior R médio por trade "
             f"(custos base) entre variantes com >= {MIN_TRAIN_TRADES} trades de treino (senão: a com mais trades). 6 campeões. "
             "Validação 2025-12-14→2026-02-01 (10% do DEV) = só porta V1, não re-selecciona. Holdout 2026-02-01→2026-10-01 avaliado "
             "UMA vez para os 6 campeões. Holdout das outras variantes = só diagnóstico, calculado depois, não muda nada.")
CRITERIA = ["V1 validação: R médio do campeão > 0",
            f"V2 holdout: R médio por trade > 0 com >= {MIN_OOS_TRADES} trades (custos base)",
            "V3 holdout: bootstrap estacionário (bloco 5 dias) da média diária > 0, p Holm (6 campeões) < 0.05",
            f"V4 DSR do campeão (série diária de treino) > 0.95 com N = variantes deste estudo + {PRIOR_TRIALS} anteriores do projecto",
            "V5 White Reality Check no treino (todas as variantes vs caixa, B=1000, bloco 5 dias) p < 0.05",
            "V6 walk-forward 90d→30d dentro do DEV (mesma família e execução): R médio > 0",
            f"V7 holdout com slippage dobrada ({SLIP_STRESS * 1e4:.0f} bp): R médio > 0",
            "V8 holdout: max drawdown da série diária (sem travas da conta) <= 20%",
            "VALIDADA = V1..V8 todas; qualquer falha = NAO_VALIDADA. Só VALIDADA justifica um bot de scalping em paper."]


def prereg_doc():
    vs = variants()
    return {"note": "escrito ANTES de correr qualquer variante nos dados reais; run recusa se o hash não bater ou o código divergir",
            "data": {"src": DIR + " (data.binance.vision 1m, USDT como proxy de USD na Revolut X)", "symbols": SYMS, "tf_min": [1, 5],
                     "bad_bar_rule": f"barra em falta/inválida → preenchida com o fecho anterior e bloqueia entradas {BLOCK_AFTER_BAD} barras"},
            "windows": {"dev": [DEV0, OOS0], "train": [DEV0, VAL0], "validation": [VAL0, OOS0], "holdout": [OOS0, OOS1],
                        "walk_forward": f"{WF_TRAIN_D}d treino → {WF_TEST_D}d teste, passo {WF_TEST_D}d, min {WF_MIN} trades"},
            "execution": {"signal": "fecho da barra t", "taker_entry": "abertura t+1 + slippage", "maker_entry": f"limite = fecho t, válida {LIMIT_VALID} barras, enche só se low < limite",
                          "stop": "sempre taker; abertura abaixo do stop → abertura; stop e alvo na mesma barra → stop", "target_maker": "limite, enche só se high > alvo",
                          "time_stop": "fecho com barras >= tstop → abertura seguinte taker", "one_position_per_pair": True,
                          "atr_table": [[0.0015, 1.0, 1.5], [0.0035, 1.5, 2.0], ["inf", 2.0, 3.0]],
                          "S1_target": "banda do meio (da barra anterior)", "S2_invalidation": "fecho < EMA21", "S3_squeeze": "BB(20,2) largura <= percentil em alguma das 5 barras anteriores (janela 240), fecho > máx 20 barras, vol > k×média 20, largura a subir"},
            "costs": {"taker_fee": TAKER, "maker_fee": MAKER_FEE, "slippage": SLIP, "slippage_stress": SLIP_STRESS},
            "sizing": {"risk": RISK, "pos_cap": POS_CAP, "max_open": MAX_OPEN, "start_usd": START_USD, "day_halt": DAY_HALT, "peak_breaker": PEAK_BREAKER},
            "variants": [v["id"] for v in vs], "n_variants": len(vs), "prior_trials_project": PRIOR_TRIALS,
            "selection": SELECTION, "criteria": CRITERIA}


def phase_prereg():
    doc = prereg_doc(); doc["sha256"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    json.dump(doc, open(PREREG, "w"), indent=1); print(doc["n_variants"], doc["sha256"]); return doc


def check_prereg(path=PREREG):
    doc = json.load(open(path)); h = doc.pop("sha256")
    if hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest() != h: raise SystemExit("pré-registo alterado: abortado")
    if doc != json.loads(json.dumps(prereg_doc())): raise SystemExit("código diverge do pré-registo: abortado")
    return h


# ---------------- fases ----------------
def load_all():
    out = {}
    for s in SYMS:
        raw = load_1m(s); g1 = to_grid(raw); g5 = resample(g1)
        out[s] = {1: (g1, features(g1)), 5: (g5, features(g5)), "q": quality(raw, g1)}
    return out


def phase_quality():
    os.makedirs(STATE, exist_ok=True); q = {}
    for s in SYMS:
        raw = load_1m(s); q[s] = quality(raw, to_grid(raw))
    json.dump(q, open(f"{STATE}/data_quality.json", "w"), indent=1); print(json.dumps(q, indent=1)); return q


def run_all_pairs(v, data, t0, t1, slip=SLIP, fee=TAKER):
    tf = v["params"]["tf"]; return merge([run_variant(v, *data[s][tf], t0, t1, slip=slip, fee=fee) for s in SYMS])


def phase_run():
    from desk.research.sweep import reality_check
    h = check_prereg(); os.makedirs(STATE, exist_ok=True)
    data = load_all(); vs = variants(); N_proj = len(vs) + PRIOR_TRIALS
    DEVT = {v["id"]: run_all_pairs(v, data, DEV0, OOS0) for v in vs}                      # só DEV (treino + validação)
    TR = {k: subset(T, DEV0, VAL0) for k, T in DEVT.items()}; VA = {k: subset(T, VAL0, OOS0) for k, T in DEVT.items()}
    S_tr = {k: stats(T, DEV0, VAL0) for k, T in TR.items()}
    Rtr = np.array([daily_series(TR[v["id"]], DEV0, VAL0) for v in vs])
    sr_all = np.array([x.mean() / x.std(ddof=1) if x.std() > 0 else 0.0 for x in Rtr])
    rc = reality_check(Rtr, B=1000, mean_block=5)
    champs = {}
    for fam in FAMILIES:
        for ex in ("taker", "maker"):
            fv = [v for v in vs if v["fam"] == fam and v["params"]["exec"] == ex]
            el = [v for v in fv if S_tr[v["id"]]["trades"] >= MIN_TRAIN_TRADES]
            ch = max(el, key=lambda v: S_tr[v["id"]]["exp_r"]) if el else max(fv, key=lambda v: S_tr[v["id"]]["trades"])
            k = vs.index(ch); wf = walk_forward({v["id"]: DEVT[v["id"]] for v in fv})
            champs[f"{fam}|{ex}"] = {"id": ch["id"], "params": ch["params"], "train": S_tr[ch["id"]], "val": stats(VA[ch["id"]], VAL0, OOS0),
                                     "dsr_study_N": dsr_n(Rtr[k], sr_all, len(vs)), "dsr_project_N": dsr_n(Rtr[k], sr_all, N_proj),
                                     "walk_forward": wf, "family_frac_train_exp_pos": float(np.mean([S_tr[v["id"]]["exp_r"] > 0 for v in fv]))}
    # ---- holdout: UMA vez, só campeões ----
    for key, c in champs.items():
        v = next(x for x in vs if x["id"] == c["id"])
        T = run_all_pairs(v, data, OOS0, OOS1); Ts = run_all_pairs(v, data, OOS0, OOS1, slip=SLIP_STRESS)
        c["oos"] = stats(T, OOS0, OOS1); c["oos_stress"] = stats(Ts, OOS0, OOS1); c["oos_account"] = account(T)
        c["oos_by_pair"] = {s: stats({k: (x[T["pair"] == j] if isinstance(x, np.ndarray) else 0) for k, x in T.items()}, OOS0, OOS1)["exp_r"]
                            for j, s in enumerate(SYMS)}
        c["boot_p"] = float(boot_p_mean(daily_series(T, OOS0, OOS1)))
    adj = holm(np.array([c["boot_p"] for c in champs.values()]))
    for (key, c), pa in zip(champs.items(), adj):
        c["boot_p_holm"] = float(pa); o = c["oos"]
        chk = {"V1": c["val"]["exp_r"] > 0, "V2": o["exp_r"] > 0 and o["trades"] >= MIN_OOS_TRADES, "V3": pa < 0.05,
               "V4": c["dsr_project_N"] > 0.95, "V5": rc["p"] < 0.05, "V6": c["walk_forward"]["exp_r"] > 0,
               "V7": c["oos_stress"]["exp_r"] > 0, "V8": o["max_dd"] <= 0.20}
        c["checks"] = {k: bool(x) for k, x in chk.items()}; c["verdict"] = "VALIDADA" if all(chk.values()) else "NAO_VALIDADA"
        c["auditor_like"] = {"trades>=40": o["trades"] >= 40, "wr>=33%": o["win_rate"] >= 0.33, "exp>=+0.4R": o["exp_r"] >= 0.4, "dd<=20%": o["max_dd"] <= 0.2}
    # ---- diagnóstico (depois dos veredictos; não muda nada) ----
    diag = {}
    for v in vs:
        T = run_all_pairs(v, data, OOS0, OOS1); s = stats(T, OOS0, OOS1)
        diag[v["id"]] = {"train_exp_r": S_tr[v["id"]]["exp_r"], "train_trades": S_tr[v["id"]]["trades"], "val_exp_r": stats(VA[v["id"]], VAL0, OOS0)["exp_r"],
                         "oos_exp_r": s["exp_r"], "oos_trades": s["trades"], "oos_wr": s["win_rate"], "oos_tpd": s["trades_per_day"]}
    # efeito das taxas: mesmo par (variante taker ↔ mesma variante maker)
    fee = []
    for v in vs:
        if v["params"]["exec"] != "taker": continue
        m = v["id"].replace("exec=taker", "exec=maker"); fee.append((diag[v["id"]]["oos_exp_r"], diag[m]["oos_exp_r"], diag[v["id"]]["train_exp_r"], diag[m]["train_exp_r"]))
    fee = np.array(fee)
    rep = {"prereg_sha256": h, "n_variants": len(vs), "n_project_cum": N_proj, "rc_train_vs_cash": rc, "champions": champs,
           "data_quality": {s: data[s]["q"] for s in SYMS},
           "train_all": {k: {kk: S_tr[k][kk] for kk in ("trades", "exp_r", "win_rate", "trades_per_day", "sharpe")} for k in S_tr},
           "frac_train_exp_pos": float(np.mean([S_tr[v["id"]]["exp_r"] > 0 for v in vs])),
           "diagnostic_oos_all": diag, "frac_oos_exp_pos_diag": float(np.mean([d["oos_exp_r"] > 0 for d in diag.values()])),
           "fee_effect_pairs": {"n_pairs": len(fee), "train_mean_taker": float(fee[:, 2].mean()), "train_mean_maker": float(fee[:, 3].mean()),
                                "oos_mean_taker": float(fee[:, 0].mean()), "oos_mean_maker": float(fee[:, 1].mean()),
                                "oos_frac_maker_better": float((fee[:, 1] > fee[:, 0]).mean()), "oos_n_maker_pos": int((fee[:, 1] > 0).sum()),
                                "oos_n_taker_pos": int((fee[:, 0] > 0).sum())}}
    json.dump(rep, open(f"{STATE}/scalp_report.json", "w"), indent=1, default=float)
    for key, c in champs.items():
        o = c["oos"]
        print(f"{key:32s} {c['id'].split(':')[1]:42s} trR={c['train']['exp_r']:+.3f} vaR={c['val']['exp_r']:+.3f} OOS R={o['exp_r']:+.3f} "
              f"wr={o['win_rate']:.0%} n={o['trades']} tpd={o['trades_per_day']:.1f} dd={o['max_dd']:.1%} S={o['sharpe']:+.2f} "
              f"dsrP={c['dsr_project_N']:.2f} p={c['boot_p_holm']:.3f} wf={c['walk_forward']['exp_r']:+.3f} {c['verdict']} {c['checks']}")
    print("RC", rc, "fee", rep["fee_effect_pairs"])
    return rep


def phase_posthoc():
    """DIAGNÓSTICO pós-holdout (não muda veredictos): os 6 campeões SEM custos (taxa 0, slippage 0) — há sinal antes dos custos?
    E o custo de ida e volta taker medido em R (custo / distância média do stop)."""
    rep = json.load(open(f"{STATE}/scalp_report.json")); data = load_all(); vs = variants(); out = {}
    for key, c in rep["champions"].items():
        v = next(x for x in vs if x["id"] == c["id"])
        tr = stats(run_all_pairs(v, data, DEV0, VAL0, slip=0.0, fee=0.0), DEV0, VAL0)
        oo = stats(run_all_pairs(v, data, OOS0, OOS1, slip=0.0, fee=0.0), OOS0, OOS1)
        out[key] = {"id": c["id"], "train_gross_exp_r": tr["exp_r"], "oos_gross_exp_r": oo["exp_r"], "oos_gross_wr": oo["win_rate"],
                    "oos_net_exp_r": c["oos"]["exp_r"], "taker_roundtrip_cost_in_r": (2 * TAKER + 2 * SLIP) / c["oos"]["avg_stop_dist"]}
        print(key, {k: round(x, 3) if isinstance(x, float) else x for k, x in out[key].items()})
    json.dump(out, open(f"{STATE}/posthoc.json", "w"), indent=1, default=float); return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=["quality", "prereg", "run", "posthoc"]); a = ap.parse_args()
    {"quality": phase_quality, "prereg": phase_prereg, "run": phase_run, "posthoc": phase_posthoc}[a.phase]()


if __name__ == "__main__":
    main()
