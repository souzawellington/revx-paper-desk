"""Simulação CONSERVADORA de market making passivo long-only (ideias de Hummingbot pure MM / Avellaneda-Stoikov,
Apache-2.0, re-implementadas). Só simulação; nunca envia ordens. Dados: fita pública de trades Revolut X (desk/revx_tape.py).

Modelo (pré-registado em DESK_RULES.md, secção Market making):
- Capital mm_capital_usd (≈ £50) em USD; spot long-only: só vende o inventário que tem; sem short, sem alavancagem.
- Requote a cada mm_requote_s; cada requote coloca ≤2 ordens (≤ 1000 ordens/dia verificado).
- Mid(t) = mediana dos últimos 20 trades ANTES de t (sem look-ahead). σ = desvio-padrão dos log-retornos de 1 min
  da última hora, escalado para mm_requote_s.
- Half-spread h = max(mm_min_half_bps, 1/κ) + 0.5·σ ; κ ajustado SÓ no in-sample (λ(δ) = A·e^(−κδ) dos trades que
  atravessam mid±δ em janelas de requote). Variante WIDE: h × mm_wide_mult.
- Inventário (A-S, alvo 0% base): q = valor_base / equity ∈ [0,1]; reservation r = mid·(1 − q·h) (skew para vender).
  bid = r·(1−h) se q < mm_max_inv_frac; ask = r·(1+h) só se há inventário (vende ≤ inventário).
- Fills PESSIMISTAS: ordem activa só após mm_latency_s; bid enche só com trades de VENDA (agressor sell) a preço
  ESTRITAMENTE abaixo do bid (fila à frente absorve tudo ao nosso preço), e só mm_queue_share da quantidade desse trade.
  Ask simétrico com agressor buy. Maker 0%.
- Hard-stop de inventário −8% sobre o custo médio → venda a mercado no trade seguinte com taker 0.09% + slippage 0.1%.
  No fim do período liquida-se o inventário igual (taker + slippage).
- Métricas: PnL, bps por round-trip (FIFO), WR, R = PnL_rt / (notional_rt × 8%) [mapeamento para o auditor; limiares NÃO
  relaxados], max DD da equity mark-to-market, inventário médio/máximo, markout de 60 s/300 s dos fills (selecção adversa).
"""
from __future__ import annotations
import argparse, bisect, json, math, os, statistics
from .rules import load_rules
from . import revx_tape

D = 86_400_000


def _g(rules, k, d):
    try: return rules.p.get(k, d)
    except AttributeError: return d


def mid_at(prices, times, t, n=20):
    i = bisect.bisect_left(times, t)
    if i < 5: return None
    return statistics.median(prices[max(0, i - n):i])


def sigma_at(prices, times, t, horizon_s):
    """σ (fracção) para horizon_s a partir de retornos de 1 min da última hora antes de t."""
    pts = []
    for k in range(61):
        tt = t - (60 - k) * 60_000; i = bisect.bisect_left(times, tt)
        if i == 0: continue
        pts.append(prices[i - 1])
    r = [math.log(b / a) for a, b in zip(pts[:-1], pts[1:]) if a > 0 and b > 0]
    if len(r) < 20: return None
    return statistics.pstdev(r) * math.sqrt(horizon_s / 60)


def fit_kappa(tape, t0, t1, rules):
    """Ajusta κ (em 1/fracção) só em [t0,t1): λ(δ)=frequência de janelas com trade de venda abaixo de mid·(1−δ)."""
    times = [x["ts"] for x in tape]; prices = [x["px"] for x in tape]
    step = int(_g(rules, "mm_requote_s", 300)) * 1000; lat = int(_g(rules, "mm_latency_s", 2) * 1000)
    grid = [b / 1e4 for b in (1, 2, 3, 5, 8, 13, 20, 30, 50)]; hits = [0] * len(grid); nwin = 0
    t = t0
    while t + step <= t1:
        m = mid_at(prices, times, t)
        if m:
            nwin += 1
            i, j = bisect.bisect_left(times, t + lat), bisect.bisect_left(times, t + step)
            lows = [tape[k]["px"] for k in range(i, j) if tape[k]["side"] == "sell"]
            mn = min(lows) if lows else None
            for g, d in enumerate(grid):
                if mn is not None and mn < m * (1 - d): hits[g] += 1
        t += step
    pts = [(d, math.log(h / nwin)) for d, h in zip(grid, hits) if h > 0 and nwin]
    if len(pts) < 3: return None, {"windows": nwin, "hits": hits}
    xs, ys = zip(*pts); mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x in xs)
    return max(1e-6, -slope), {"windows": nwin, "hits": dict(zip([round(d * 1e4) for d in grid], hits)), "A": math.exp(my - slope * mx)}


def simulate(tape, t0, t1, rules, kappa, wide=1.0, touch=False):
    cap = float(_g(rules, "mm_capital_usd", 65)); size = float(_g(rules, "mm_order_usd", 20))
    step = int(_g(rules, "mm_requote_s", 300)) * 1000; lat = int(float(_g(rules, "mm_latency_s", 2)) * 1000)
    qs = float(_g(rules, "mm_queue_share", 0.5)); hmin = float(_g(rules, "mm_min_half_bps", 2)) / 1e4
    maxinv = float(_g(rules, "mm_max_inv_frac", 0.6)); hard = float(rules.hard_stop_pct)
    taker, slip = float(rules.taker_fee), float(rules.slippage)
    times = [x["ts"] for x in tape]; prices = [x["px"] for x in tape]
    usd, base, cost = cap, 0.0, 0.0           # cost = custo total do inventário (para preço médio)
    lots, rts, fills, curve, orders_by_day = [], [], [], [], {}
    peak, mdd, inv_samples, stops = cap, 0.0, [], 0
    t = t0; last_px = None
    while t + step <= t1:
        m = mid_at(prices, times, t); s = sigma_at(prices, times, t, step / 1000)
        i, j = bisect.bisect_left(times, t + lat), bisect.bisect_left(times, t + step)
        if m is None or s is None:
            t += step; continue
        h = (max(hmin, 1.0 / kappa) + 0.5 * s) * wide
        eq = usd + base * m; q = (base * m) / eq if eq > 0 else 0.0
        r = m * (1 - q * h)
        bid, ask = r * (1 - h), r * (1 + h)
        bid_qty = (min(size, usd) / bid) if (q < maxinv and usd >= 1.0) else 0.0
        ask_qty = min(base, size / ask) if base * m >= 0.1 else 0.0
        day = t // D; orders_by_day[day] = orders_by_day.get(day, 0) + (bid_qty > 0) + (ask_qty > 0)
        for k in range(i, j):
            tr = tape[k]; px = tr["px"]; last_px = px
            # hard-stop de inventário (sobre custo médio)
            if base > 0 and px <= (cost / base) * (1 - hard):
                out = px * (1 - slip); proceeds = base * out * (1 - taker)
                _close_lots(lots, rts, base, out, taker, tr["ts"], "HARD_STOP"); usd += proceeds; base, cost = 0.0, 0.0
                stops += 1; ask_qty = 0.0; bid_qty = 0.0; continue
            if bid_qty > 0 and tr["side"] == "sell" and (px < bid or (touch and px <= bid)):
                f = min(bid_qty, qs * tr["qty"]); bid_qty -= f
                usd -= f * bid; base += f; cost += f * bid; lots.append([f, bid, tr["ts"]])
                fills.append({"ts": tr["ts"], "side": "buy", "px": bid, "qty": f})
            elif ask_qty > 0 and tr["side"] == "buy" and (px > ask or (touch and px >= ask)):
                f = min(ask_qty, qs * tr["qty"], base); ask_qty -= f
                avg = cost / base if base > 0 else ask
                usd += f * ask; base -= f; cost -= f * avg
                _close_lots(lots, rts, f, ask, 0.0, tr["ts"], "MAKER")
                fills.append({"ts": tr["ts"], "side": "sell", "px": ask, "qty": f})
        mm = mid_at(prices, times, t + step) or m
        e = usd + base * mm; curve.append((t + step, e)); inv_samples.append(base * mm / e if e > 0 else 0)
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak)
        t += step
    if base > 0 and last_px:
        out = last_px * (1 - slip); usd += base * out * (1 - taker); _close_lots(lots, rts, base, out, taker, t, "END_LIQ"); base = 0.0
    # markouts
    for f in fills:
        for lag in (60, 300):
            mk = mid_at(prices, times, f["ts"] + lag * 1000)
            if mk: f[f"mk{lag}_bps"] = ((mk / f["px"] - 1) if f["side"] == "buy" else (f["px"] / mk - 1)) * 1e4
    return {"equity_end": usd, "pnl_usd": usd - cap, "pnl_bps_capital": (usd / cap - 1) * 1e4, "max_dd": mdd,
            "round_trips": rts, "fills": len(fills), "buys": sum(f["side"] == "buy" for f in fills),
            "inv_avg": sum(inv_samples) / len(inv_samples) if inv_samples else 0.0, "inv_max": max(inv_samples, default=0.0),
            "hard_stops": stops, "orders_per_day_max": max(orders_by_day.values(), default=0),
            "markout60_bps": _mean([f.get("mk60_bps") for f in fills]), "markout300_bps": _mean([f.get("mk300_bps") for f in fills]),
            "kappa": kappa, "half_spread_floor_bps": max(hmin, 1 / kappa) * 1e4 * wide}


def _mean(xs):
    xs = [x for x in xs if x is not None]; return sum(xs) / len(xs) if xs else None


def _close_lots(lots, rts, qty, px, fee, ts, why):
    """FIFO: fecha `qty` contra lotes comprados. Cada lote fechado (parcial) = um round trip."""
    while qty > 1e-15 and lots:
        lq, lp, lt = lots[0]; f = min(lq, qty)
        pnl = f * px * (1 - fee) - f * lp
        rts.append({"entry_ts": lt, "exit_ts": ts, "qty": f, "buy": lp, "sell": px, "pnl": pnl, "notional": f * lp,
                    "bps": (px * (1 - fee) / lp - 1) * 1e4, "why": why})
        lots[0][0] -= f; qty -= f
        if lots[0][0] <= 1e-15: lots.pop(0)


def score_rts(rts, hard=0.08):
    n = len(rts)
    if not n: return {"n": 0, "win_rate": 0.0, "bps_mean": 0.0, "expectancy_r": 0.0, "notional_weighted_bps": 0.0}
    w = sum(r["pnl"] > 0 for r in rts); nt = sum(r["notional"] for r in rts)
    return {"n": n, "win_rate": w / n, "bps_mean": sum(r["bps"] for r in rts) / n,
            "notional_weighted_bps": sum(r["pnl"] for r in rts) / nt * 1e4 if nt else 0.0,
            "expectancy_r": sum(r["pnl"] / (r["notional"] * hard) for r in rts) / n}


def run(symbols, tape_dir, rules, split=0.6):
    out = {}
    for s in symbols:
        tape = [x for x in revx_tape.load(tape_dir, s) if x.get("side") in ("buy", "sell")]
        if len(tape) < 1000: out[s] = {"status": "INSUFFICIENT_DATA", "trades": len(tape)}; continue
        t0 = tape[0]["ts"] // D * D; t1 = tape[-1]["ts"] // D * D + D
        cut = t0 + int((t1 - t0) * split) // D * D
        kappa, kinfo = fit_kappa(tape, t0, cut, rules)
        if kappa is None: out[s] = {"status": "INSUFFICIENT_DATA", "kappa_fit": kinfo}; continue
        res = {"trades_tape": len(tape), "t0": t0, "cut": cut, "t1": t1, "kappa": kappa, "kappa_fit": kinfo}
        for name, wide in (("MM_AS", 1.0), ("MM_WIDE", float(_g(rules, "mm_wide_mult", 2.0)))):
            ins = simulate(tape, t0, cut, rules, kappa, wide); oos = simulate(tape, cut, t1, rules, kappa, wide)
            full = simulate(tape, t0, t1, rules, kappa, wide)
            res[name] = {k: {**{kk: v for kk, v in r.items() if kk != "round_trips"}, "rt": score_rts(r["round_trips"], rules.hard_stop_pct),
                             "exit_reasons": _reasons(r["round_trips"])} for k, r in (("in_sample", ins), ("oos", oos), ("full", full))}
        out[s] = res
    return out


class _Over:
    """Rules com overrides (só para o diagnóstico de sensibilidade; não altera DESK_RULES)."""
    def __init__(self, rules, **kw): self._r = rules; self.p = {**rules.p, **kw}
    def __getattr__(self, k): return self.p[k] if k in self.p else getattr(self._r, k)


def sensitivity(tape_dir, symbols, rules):
    """DIAGNÓSTICO NÃO PROMOVÍVEL: cenário OPTIMISTA (fill ao toque, 100% da quantidade, latência 0) e κ do in-sample.
    Se nem assim houver edge, o resultado pessimista não é artefacto do modelo de fills."""
    opt = _Over(rules, mm_queue_share=1.0, mm_latency_s=0); out = {}
    for s in symbols:
        tape = [x for x in revx_tape.load(tape_dir, s) if x.get("side") in ("buy", "sell")]
        if len(tape) < 1000: continue
        t0 = tape[0]["ts"] // D * D; t1 = tape[-1]["ts"] // D * D + D; cut = t0 + int((t1 - t0) * 0.6) // D * D
        k, _ = fit_kappa(tape, t0, cut, rules)
        if not k: continue
        for name, wide in (("MM_AS", 1.0), ("MM_WIDE", float(_g(rules, "mm_wide_mult", 2.0)))):
            r = simulate(tape, cut, t1, opt, k, wide, touch=True); sc = score_rts(r["round_trips"], rules.hard_stop_pct)
            out[f"{s}:{name}:oos_optimista"] = {"n": sc["n"], "bps_rt": sc["bps_mean"], "R": sc["expectancy_r"], "pnl_usd": r["pnl_usd"],
                                                "max_dd": r["max_dd"], "markout300_bps": r["markout300_bps"]}
    return out


def _reasons(rts):
    c = {}
    for r in rts: c[r["why"]] = c.get(r["why"], 0) + 1
    return c


def verdict(res, rules):
    """Auditor com limiares CONGELADOS (R mapeado = PnL_rt / (notional × 8%))."""
    v = {}
    for s, r in res.items():
        if "MM_AS" not in r: v[s] = "INSUFFICIENT_DATA"; continue
        for name in ("MM_AS", "MM_WIDE"):
            f = r[name]["full"]; rt = f["rt"]; o = r[name]["oos"]["rt"]
            ok = (rt["n"] >= rules.threshold_trades and rt["win_rate"] >= rules.threshold_win_rate and
                  rt["expectancy_r"] >= rules.threshold_expectancy_r and f["max_dd"] <= rules.threshold_max_dd and o["expectancy_r"] > 0
                  and o["n"] >= max(10, rules.threshold_trades // 2))
            v[f"{s}:{name}"] = "DATA_VALIDATED" if ok else ("TRADE_OFF" if rt["n"] >= rules.threshold_trades else "NO_EDGE")
    return v


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols", default="BTC,ETH,SOL,DOGE"); ap.add_argument("--tape", default="data_tape")
    ap.add_argument("--out", default="desk/state/mm_report.json"); a = ap.parse_args(); rules = load_rules()
    syms = [f"{x.strip().upper()}-USD" for x in a.symbols.split(",")]
    res = run(syms, a.tape, rules); v = verdict(res, rules)
    sens = sensitivity(a.tape, syms, rules)
    json.dump({"results": res, "verdict": v, "sensitivity_optimistic_not_promotable": sens}, open(a.out, "w"), indent=1, default=str)
    for s, r in res.items():
        if "MM_AS" not in r: print(s, r); continue
        print(s, f"tape={r['trades_tape']} kappa={r['kappa']:.0f} (1/κ={1e4 / r['kappa']:.1f} bps)")
        for name in ("MM_AS", "MM_WIDE"):
            for k in ("in_sample", "oos", "full"):
                x = r[name][k]; rt = x["rt"]
                print(f"  {name:7} {k:9} rt n={rt['n']:4d} WR={rt['win_rate']:.1%} {rt['bps_mean']:+.1f}bps/rt R={rt['expectancy_r']:+.3f} "
                      f"PnL=${x['pnl_usd']:+.2f} ({x['pnl_bps_capital']:+.0f}bps cap) DD={x['max_dd']:.1%} inv_avg={x['inv_avg']:.0%} "
                      f"mk60={x['markout60_bps'] if x['markout60_bps'] is None else round(x['markout60_bps'], 1)} stops={x['hard_stops']} ord/d={x['orders_per_day_max']}")
    print(json.dumps(v, indent=1)); print("SENSIBILIDADE optimista (não promovível):")
    for k, x in sens.items(): print(f"  {k}: n={x['n']} {x['bps_rt']:+.1f}bps/rt R={x['R']:+.3f} PnL=${x['pnl_usd']:+.2f} mk300={x['markout300_bps']}")


if __name__ == "__main__":
    main()
