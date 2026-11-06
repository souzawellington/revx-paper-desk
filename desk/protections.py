"""PROTECTIONS + PAIR FILTERS — ideias do freqtrade (GPL-3.0) RE-IMPLEMENTADAS do zero a partir da documentação
(nenhum código copiado). Tudo é veto-only: bloqueia novos ENTRY, nunca abre, nunca aumenta, nunca toca em saídas.

Protections (sobre trades fechados do desk, paper/hipotéticos):
- CooldownPeriod   : após fecho num par, sem nova entrada nesse par durante prot_cooldown_hours.
- StoplossGuard    : ≥ prot_slguard_trades stop-outs (STOP/HARD_STOP*) em prot_slguard_lookback_h → bloqueio global prot_slguard_lock_h.
- MaxDrawdown      : drawdown do PnL realizado dentro de prot_maxdd_lookback_h (≥ prot_maxdd_min_trades trades)
                     > prot_maxdd_pct × equity → bloqueio global prot_maxdd_lock_h.
- LowProfitPairs   : par com ≥ prot_lowprofit_trades trades em prot_lowprofit_lookback_h e soma de R < prot_lowprofit_min_r
                     → par bloqueado prot_lowprofit_lock_h.
Um bloqueio dura `lock_h` a partir do evento que o disparou (como no freqtrade).

Pair filters (sobre velas 1D FECHADAS):
- AgeFilter        : ≥ filt_min_days velas 1D.
- VolumeFilter     : mediana(volume×close) dos últimos 30 dias ≥ filt_min_quote_vol (USD).
- VolatilityFilter : desvio-padrão dos retornos log diários (filt_vol_days) dentro de [filt_min_vol, filt_max_vol].
- SpreadFilter     : (ask−bid)/ask ≤ filt_max_spread quando o ticker tem bid/ask; sem ticker → INSUFFICIENT_DATA (sem efeito).
Dados insuficientes num filtro → INSUFFICIENT_DATA (não veta, não aprova nada extra).
"""
from __future__ import annotations
import math

H = 3_600_000
STOP_REASONS = ("STOP", "STOP_GAP", "HARD_STOP_8PCT", "HARD_STOP_8PCT_GAP")


def _g(rules, k, d):
    try: return rules.p.get(k, d)
    except AttributeError: return d


def mode(rules): return _g(rules, "protections_mode", "shadow")


def locks(closed, now, equity, rules):
    """closed: [{symbol, exit_ts(ms), net_r, why, pnl}]. Devolve {"global": [motivos], "pairs": {sym: [motivos]}}."""
    out = {"global": [], "pairs": {}}
    past = sorted((t for t in closed if t["exit_ts"] <= now), key=lambda t: t["exit_ts"])
    # CooldownPeriod (por par)
    cd = float(_g(rules, "prot_cooldown_hours", 4)) * H
    for t in past:
        if now - t["exit_ts"] < cd: out["pairs"].setdefault(t["symbol"], []).append("COOLDOWN")
    # StoplossGuard (global): avaliado em cada stop-out; lock a partir do stop que completa o limite
    lb, n_lim, lk = (float(_g(rules, "prot_slguard_lookback_h", 24)) * H, int(_g(rules, "prot_slguard_trades", 4)),
                     float(_g(rules, "prot_slguard_lock_h", 4)) * H)
    stops = [t for t in past if t["why"] in STOP_REASONS]
    for i, t in enumerate(stops):
        win = [s for s in stops[:i + 1] if t["exit_ts"] - s["exit_ts"] <= lb]
        if len(win) >= n_lim and now - t["exit_ts"] < lk:
            out["global"].append(f"STOPLOSS_GUARD:{len(win)}stops/{int(lb / H)}h"); break
    # MaxDrawdown (global, PnL realizado na janela)
    lb, n_min, pct, lk = (float(_g(rules, "prot_maxdd_lookback_h", 168)) * H, int(_g(rules, "prot_maxdd_min_trades", 5)),
                          float(_g(rules, "prot_maxdd_pct", 0.05)), float(_g(rules, "prot_maxdd_lock_h", 48)) * H)
    for i, t in enumerate(past):
        if now - t["exit_ts"] >= lk: continue
        win = [s for s in past[:i + 1] if t["exit_ts"] - s["exit_ts"] <= lb]
        if len(win) < n_min or equity <= 0: continue
        cum = peak = mdd = 0.0
        for s in win:
            cum += s.get("pnl", 0.0); peak = max(peak, cum); mdd = max(mdd, peak - cum)
        if mdd / equity > pct:
            out["global"].append(f"MAX_DRAWDOWN:{mdd / equity:.1%}>{pct:.0%}"); break
    # LowProfitPairs (por par)
    lb, n_lim, min_r, lk = (float(_g(rules, "prot_lowprofit_lookback_h", 720)) * H, int(_g(rules, "prot_lowprofit_trades", 2)),
                            float(_g(rules, "prot_lowprofit_min_r", 0.0)), float(_g(rules, "prot_lowprofit_lock_h", 168)) * H)
    by = {}
    for t in past: by.setdefault(t["symbol"], []).append(t)
    for sym, ts in by.items():
        for i, t in enumerate(ts):
            if now - t["exit_ts"] >= lk: continue
            win = [s for s in ts[:i + 1] if t["exit_ts"] - s["exit_ts"] <= lb]
            if len(win) >= n_lim and sum(s["net_r"] for s in win) < min_r:
                out["pairs"].setdefault(sym, []).append(f"LOW_PROFIT_PAIR:{sum(s['net_r'] for s in win):+.2f}R/{len(win)}"); break
    return out


def blocked(sym, lk):
    return lk["global"] + lk["pairs"].get(sym, [])


# ---------------- pair filters ----------------
def pair_filters(d1, rules, ticker=None):
    """Devolve {"reasons": [vetos], "checks": {filtro: valor|INSUFFICIENT_DATA}}."""
    reasons, checks = [], {}
    n_min = int(_g(rules, "filt_min_days", 30))
    checks["age_days"] = len(d1)
    if len(d1) < n_min: reasons.append(f"AGE_FILTER:{len(d1)}<{n_min}d")
    if len(d1) >= 30:
        qv = sorted(x.get("volume", 0.0) * x["close"] for x in d1[-30:]); med = qv[len(qv) // 2]
        checks["median_quote_vol"] = round(med, 2)
        if med < float(_g(rules, "filt_min_quote_vol", 50_000)): reasons.append(f"VOLUME_FILTER:{med:,.0f}<{_g(rules, 'filt_min_quote_vol', 50_000):,}")
    else: checks["median_quote_vol"] = "INSUFFICIENT_DATA"
    k = int(_g(rules, "filt_vol_days", 10))
    if len(d1) > k:
        cl = [x["close"] for x in d1[-(k + 1):]]
        lr = [math.log(b / a) for a, b in zip(cl[:-1], cl[1:]) if a > 0 and b > 0]
        if len(lr) >= 2:
            m = sum(lr) / len(lr); sd = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1))
            checks["daily_vol"] = round(sd, 4)
            lo, hi = float(_g(rules, "filt_min_vol", 0.005)), float(_g(rules, "filt_max_vol", 0.15))
            if not lo <= sd <= hi: reasons.append(f"VOLATILITY_FILTER:{sd:.3f}∉[{lo},{hi}]")
        else: checks["daily_vol"] = "INSUFFICIENT_DATA"
    else: checks["daily_vol"] = "INSUFFICIENT_DATA"
    try:
        bid, ask = float(ticker["bid"]), float(ticker["ask"])
        if not (ask > 0 and bid > 0): raise ValueError
        sp = (ask - bid) / ask; checks["spread"] = round(sp, 5)
        if sp > float(_g(rules, "filt_max_spread", 0.005)): reasons.append(f"SPREAD_FILTER:{sp:.2%}>{_g(rules, 'filt_max_spread', 0.005):.2%}")
    except Exception:
        checks["spread"] = "INSUFFICIENT_DATA"
    return {"reasons": reasons, "checks": checks}


# ---------------- live: trades fechados do desk ----------------
def closed_from_positions(rows, rules):
    from . import logic as L
    out = []
    for r in rows:
        if r.get("status") != "CLOSED" or not r.get("exit_ts"): continue
        try:
            e, x, s, q = float(r["entry"]), float(r["exit"]), float(r["initial_stop"]), float(r["qty"])
            tr = L.trade_r(e, x, s, rules)
            out.append({"symbol": r["coin"], "exit_ts": int(float(r["exit_ts"])), "net_r": tr["net_r"], "why": r.get("exit_rule", ""),
                        "pnl": q * (tr["fill_out"] - tr["fill_in"]) - q * tr["fee_per_unit"]})
        except (TypeError, ValueError, KeyError):
            continue
    return out
