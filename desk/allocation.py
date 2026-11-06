"""ALOCAÇÃO HRP / CVaR (ideias e fórmulas Riskfolio-Lib, BSD-3; re-implementadas em Python puro, sem dependência).
Hierarchical Risk Parity (López de Prado 2016), como `rp.HCPortfolio(...).optimization(model="HRP",
codependence="pearson", rm="MV"|"CVaR", linkage="single", leaf_order=False)`:
  1) distância d = sqrt((1 − ρ)/2); 2) clustering single-linkage; 3) seriação (ordem das folhas);
  4) bisecção recursiva: cada metade recebe peso ∝ 1 − risco/(risco_esq + risco_dir), risco = risco da carteira
     inverse-risk do cluster (MV: variância; CVaR: CVaR histórico α).
Uso no desk: SÓ REDUZ o teto do candidato (DESK_RULES.md, secção «Alocação HRP»). Nunca aumenta, nunca abre.
"""
from __future__ import annotations
import math

OK, ABST = "OK", "INSUFFICIENT_DATA"


def _g(rules, k, d):
    try: return rules.p.get(k, d)
    except AttributeError: return d


def mode(rules): return _g(rules, "alloc_mode", "shadow")


def _mean(x): return sum(x) / len(x)


def cov(a, b):
    ma, mb = _mean(a), _mean(b); return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)


def corr(a, b):
    va, vb = cov(a, a), cov(b, b)
    return 0.0 if va <= 0 or vb <= 0 else cov(a, b) / math.sqrt(va * vb)


def cvar_hist(x, alpha=0.05):
    """Igual a riskfolio.RiskFunctions.CVaR_Hist (perda positiva)."""
    s = sorted(x); idx = int(math.ceil(alpha * len(s)) - 1)
    sum_var = sum(s[i] - s[idx] for i in range(idx + 1))
    return -s[idx] - sum_var / (alpha * len(s))


def _port(R, idx, w):
    return [sum(w[k] * R[i][t] for k, i in enumerate(idx)) for t in range(len(R[0]))]


def _risk(R, idx, w, rm, alpha):
    p = _port(R, idx, w)
    return cov(p, p) if rm == "MV" else cvar_hist(p, alpha)


def _naive(R, idx, rm, alpha):
    inv = []
    for i in idx:
        r = cov(R[i], R[i]) if rm == "MV" else cvar_hist(R[i], alpha)   # MV: 1/σ² ; CVaR: 1/CVaR
        inv.append(1.0 / r if r > 0 else 0.0)
    s = sum(inv)
    return [x / s for x in inv] if s > 0 else [1.0 / len(idx)] * len(idx)


def single_linkage_order(D):
    """Ordem das folhas de scipy.cluster.hierarchy.linkage(method='single') + leaves_list (sem optimal ordering)."""
    n = len(D); clusters = {i: [i] for i in range(n)}; nxt = n
    while len(clusters) > 1:
        best = None
        ids = sorted(clusters)
        for a_i, a in enumerate(ids):
            for b in ids[a_i + 1:]:
                d = min(D[x][y] for x in clusters[a] for y in clusters[b])
                if best is None or d < best[0] - 1e-15: best = (d, a, b)
        _, a, b = best
        clusters[nxt] = clusters.pop(a) + clusters.pop(b)   # menor id à esquerda (convenção scipy)
        nxt += 1
    return next(iter(clusters.values()))


def hrp_weights(R, rm="MV", alpha=0.05):
    """R: lista de séries de retornos alinhadas (mesmo comprimento). Devolve pesos (somam 1)."""
    n = len(R)
    if n == 1: return [1.0]
    D = [[math.sqrt(min(1.0, max(0.0, (1 - corr(R[i], R[j])) / 2))) if i != j else 0.0 for j in range(n)] for i in range(n)]
    order = single_linkage_order(D)
    w = [1.0] * n; items = [order]
    while items:
        items = [i[j:k] for i in items for j, k in ((0, len(i) // 2), (len(i) // 2, len(i))) if len(i) > 1]
        for t in range(0, len(items), 2):
            L, Rr = items[t], items[t + 1]
            rl = _risk(R, L, _naive(R, L, rm, alpha), rm, alpha); rr = _risk(R, Rr, _naive(R, Rr, rm, alpha), rm, alpha)
            a1 = 0.5 if rl + rr <= 0 else 1 - rl / (rl + rr)
            for i in L: w[i] *= a1
            for i in Rr: w[i] *= 1 - a1
    return w


def _rets_by_day(d1):
    out = {}
    for a, b in zip(d1[:-1], d1[1:]):
        if a["close"] > 0: out[b["start"]] = b["close"] / a["close"] - 1
    return out


def decision(cand, cand_d1, others: dict, rules):
    """cand: símbolo; cand_d1: velas 1D fechadas; others: {sym: velas 1D} das posições abertas.
    Devolve {status, cap_frac (≤ max_position_frac), weights, n, days, mode}."""
    mpf = float(rules.max_position_frac); rm = str(_g(rules, "alloc_rm", "MV")).upper()
    base = {"status": ABST, "cap_frac": mpf, "weights": {}, "n": 1 + len(others or {}), "days": 0, "rm": rm, "mode": mode(rules)}
    if not others or not cand_d1: return {**base, "why": "sem posições abertas" if not others else "sem velas"}
    series = {cand: _rets_by_day(cand_d1), **{s: _rets_by_day(d) for s, d in others.items() if d}}
    common = set(series[cand])
    for s in series: common &= set(series[s])
    days = sorted(common)[-int(_g(rules, "alloc_lookback_days", 90)):]
    if len(days) < int(_g(rules, "alloc_min_days", 30)) or len(series) < 2:
        return {**base, "days": len(days), "why": "histórico comum curto"}
    syms = list(series); R = [[series[s][d] for d in days] for s in syms]
    w = hrp_weights(R, "CVaR" if rm == "CVAR" else "MV")
    wc = w[syms.index(cand)]; n = len(syms)
    cap = min(mpf, wc * n * mpf)
    assert cap <= mpf + 1e-12
    return {**base, "status": OK, "cap_frac": round(cap, 6), "weights": {s: round(x, 4) for s, x in zip(syms, w)}, "n": n, "days": len(days)}


def apply(qty, entry, equity, dec, rules):
    """Só reduz: qty_nova = min(qty, cap_frac × equity / entry). Em shadow/off não muda nada."""
    if mode(rules) != "enforce" or not dec or dec.get("status") != OK or entry <= 0: return qty
    return min(qty, dec["cap_frac"] * equity / entry)


def summary(dec) -> str:
    if not dec: return ""
    if dec.get("status") != OK: return f"HRP ({dec.get('mode')}): INSUFFICIENT_DATA ({dec.get('why', '')})"
    return (f"HRP {dec['rm']} ({dec['mode']}): teto {dec['cap_frac']:.1%} do equity (N={dec['n']}, {dec['days']}d) · "
            + " ".join(f"{k} {v:.0%}" for k, v in dec["weights"].items()))
