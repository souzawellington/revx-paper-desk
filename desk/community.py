"""Estratégias da comunidade freqtrade (GPL-3.0) — lógica RE-IMPLEMENTADA a partir da descrição pública, sem copiar código.
Indicadores causais (cada valor só usa velas até i). Long-only spot, hard-stop −8% obrigatório. Ver desk/strategies/09, 10."""
from __future__ import annotations
import math

HARD = 0.08


def rsi_wilder(cl, n=14):
    out = [None] * len(cl)
    if len(cl) <= n: return out
    g = [max(b - a, 0) for a, b in zip(cl[:-1], cl[1:])]; l = [max(a - b, 0) for a, b in zip(cl[:-1], cl[1:])]
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    for i in range(n, len(cl)):
        if i > n: ag = (ag * (n - 1) + g[i - 1]) / n; al = (al * (n - 1) + l[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def bb_lower(h1, n=20, k=2.0):
    tp = [(x["high"] + x["low"] + x["close"]) / 3 for x in h1]; out = [None] * len(h1)
    for i in range(n - 1, len(h1)):
        w = tp[i - n + 1:i + 1]; m = sum(w) / n; sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        out[i] = m - k * sd
    return out


def dmi(h1, n_adx=14, n_di=25):
    """(+DI(n_di), −DI(n_di), ADX(n_adx)) de Wilder, causais."""
    L = len(h1); tr = [0.0] * L; pdm = [0.0] * L; mdm = [0.0] * L
    for i in range(1, L):
        a, b = h1[i - 1], h1[i]; up, dn = b["high"] - a["high"], a["low"] - b["low"]
        pdm[i] = up if up > dn and up > 0 else 0.0; mdm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
    def smooth(x, n):
        o = [None] * L
        if L <= n: return o
        s = sum(x[1:n + 1]); o[n] = s
        for i in range(n + 1, L): s = s - s / n + x[i]; o[i] = s
        return o
    def di(n):
        t, p, m = smooth(tr, n), smooth(pdm, n), smooth(mdm, n)
        P = [None if t[i] in (None, 0) else 100 * p[i] / t[i] for i in range(L)]
        M = [None if t[i] in (None, 0) else 100 * m[i] / t[i] for i in range(L)]
        return P, M
    p14, m14 = di(n_adx); pdi, mdi = di(n_di)
    dx = [None if p14[i] is None or (p14[i] + m14[i]) == 0 else 100 * abs(p14[i] - m14[i]) / (p14[i] + m14[i]) for i in range(L)]
    adx = [None] * L; first = next((i for i, v in enumerate(dx) if v is not None), None)
    if first is not None and first + n_adx <= L:
        a = sum(dx[first:first + n_adx]) / n_adx; adx[first + n_adx - 1] = a
        for i in range(first + n_adx, L):
            if dx[i] is None: continue
            a = (a * (n_adx - 1) + dx[i]) / n_adx; adx[i] = a
    return pdi, mdi, adx


def _sim(h1, entry_sig, exit_sig, roi, fee, slip):
    trades = []; i = 0; L = len(h1)
    while i < L - 1:
        if not entry_sig(i): i += 1; continue
        j = i + 1; entry = h1[j]["open"]; stop = entry * (1 - HARD); tp = entry * (1 + roi); px = why = None
        while j < L:
            b = h1[j]
            if b["open"] <= stop: px, why = b["open"], "STOP_GAP"
            elif b["low"] <= stop: px, why = stop, "STOP"
            elif b["high"] >= tp: px, why = max(tp, b["open"]), "ROI"
            elif exit_sig(j) and j + 1 < L: px, why = h1[j + 1]["open"], "EXIT_SIGNAL"; j += 1
            if why: break
            j += 1
        if why is None: break
        ret = (px * (1 - fee - slip)) / (entry * (1 + fee + slip)) - 1
        trades.append({"entry_ts": h1[i + 1]["start"], "exit_ts": h1[j]["start"], "net_r": ret / HARD, "why": why})
        i = j + 1
    return trades


def bbandrsi(h1, rules):
    cl = [x["close"] for x in h1]; r = rsi_wilder(cl, 14); lo = bb_lower(h1)
    ent = lambda i: r[i] is not None and lo[i] is not None and r[i] < 30 and cl[i] < lo[i]
    ex = lambda i: r[i] is not None and r[i] > 70
    return _sim(h1, ent, ex, 0.10, rules.taker_fee, rules.slippage)


def adxmomentum(h1, rules):
    cl = [x["close"] for x in h1]; pdi, mdi, adx = dmi(h1)
    mom = [None] * 14 + [cl[i] - cl[i - 14] for i in range(14, len(cl))]
    ok = lambda i: None not in (pdi[i], mdi[i], adx[i], mom[i])
    ent = lambda i: ok(i) and adx[i] > 25 and mom[i] > 0 and pdi[i] > 25 and pdi[i] > mdi[i]
    ex = lambda i: ok(i) and adx[i] > 25 and mom[i] < 0 and mdi[i] > 25 and pdi[i] < mdi[i]
    return _sim(h1, ent, ex, 0.01, rules.taker_fee, rules.slippage)
