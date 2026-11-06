"""Métricas de risco/performance DESCRITIVAS (fórmulas como no FinanceToolkit, MIT; re-implementadas em Python puro,
sem dependência). Nunca mudam o GO: os limiares congelados (trades, WR, expectancy, DD) continuam a decidir sozinhos.

Por trade (em R líquido): profit factor, payoff, SQN, Sortino (MAR 0, downside = RMS da parte negativa sobre N total),
VaR/CVaR históricos 95% (quantil com interpolação linear; CVaR = média dos valores ≤ VaR), Omega(0).
Curva de equity (diária): retorno total, max DD, duração máx. do DD (dias), Ulcer Index (pico desde o início, clip ≥ 1,
como `get_ui(rolling=None)`), Ulcer Performance Index, Calmar, Sortino anualizado (365), VaR/CVaR 95% diário, Omega(0).
"""
from __future__ import annotations
import math


def quantile(xs, q):
    """Igual a pandas.Series.quantile (interpolação linear)."""
    s = sorted(xs)
    if not s: return None
    pos = (len(s) - 1) * q; lo = math.floor(pos); hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def sortino(xs, mar=0.0):
    if not xs: return None
    ex = [x - mar for x in xs]; dd = math.sqrt(sum(min(x, 0.0) ** 2 for x in ex) / len(ex))
    return None if dd == 0 else (sum(ex) / len(ex)) / dd


def var_cvar(xs, alpha=0.05):
    if len(xs) < 2: return None, None
    v = quantile(xs, alpha); tail = [x for x in xs if x <= v]
    return v, (sum(tail) / len(tail) if tail else v)


def omega(xs, thr=0.0):
    g = sum(x - thr for x in xs if x > thr); l = sum(thr - x for x in xs if x < thr)
    return None if l == 0 else g / l


def trade_metrics(rs):
    """rs: lista de R líquidos por trade."""
    n = len(rs)
    if n == 0: return {"n": 0}
    wins = [x for x in rs if x > 0]; losses = [x for x in rs if x <= 0]
    mean = sum(rs) / n; sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    v, cv = var_cvar(rs)
    return {"n": n, "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
            "payoff": (sum(wins) / len(wins)) / (-sum(losses) / len(losses)) if wins and losses and sum(losses) < 0 else None,
            "sqn": (math.sqrt(min(n, 100)) * mean / sd) if sd > 0 else None,
            "sortino_r": sortino(rs), "var95_r": v, "cvar95_r": cv, "omega_r": omega(rs)}


def curve_metrics(equity, periods_per_year=365):
    """equity: lista de valores de equity diários (ex. curva do replay ou do journal)."""
    eq = [float(x) for x in equity if x is not None]
    if len(eq) < 3 or eq[0] <= 0: return {"days": len(eq)}
    rets = [b / a - 1 for a, b in zip(eq[:-1], eq[1:]) if a > 0]
    wealth = [1.0]
    for r in rets: wealth.append(wealth[-1] * (1 + r))
    peak = 1.0; dds = []; mdd = 0.0; dur = cur = 0
    for w in wealth[1:]:   # como o FinanceToolkit: uma observação por retorno, pico inicial = 1
        peak = max(peak, w); d = w / peak - 1; dds.append(d); mdd = min(mdd, d)
        cur = cur + 1 if d < 0 else 0; dur = max(dur, cur)
    ui = math.sqrt(sum(d * d for d in dds) / len(dds))
    total = wealth[-1] - 1; years = len(rets) / periods_per_year
    cagr = (wealth[-1] ** (1 / years) - 1) if years > 0 and wealth[-1] > 0 else None
    s = sortino(rets); v, cv = var_cvar(rets)
    return {"days": len(eq), "total_return": total, "cagr": cagr, "max_dd": -mdd, "max_dd_days": dur, "ulcer_index": ui,
            "upi": (cagr / ui) if cagr is not None and ui > 0 else None,
            "calmar": (cagr / -mdd) if cagr is not None and mdd < 0 else None,
            "sortino_ann": s * math.sqrt(periods_per_year) if s is not None else None,
            "var95_daily": v, "cvar95_daily": cv, "omega_daily": omega(rets)}


def fmt(m: dict) -> str:
    def g(k, f="{:+.2f}"):
        v = m.get(k); return "–" if v is None else f.format(v)
    return (f"PF {g('profit_factor', '{:.2f}')} · SQN {g('sqn')} · Sortino(R) {g('sortino_r')} · CVaR95 {g('cvar95_r')}R · "
            f"Omega {g('omega_r', '{:.2f}')}")
