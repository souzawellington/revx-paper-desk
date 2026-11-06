"""Texto 5 — torneio leve (5 specs). Não promove automaticamente o vencedor.
python -m desk.tournament [--symbols BTC,ETH,SOL] → desk/state/tournament_report.md
"""
from __future__ import annotations
import argparse, json, os
from dataclasses import replace
from bot.variants import resample
from .rules import load_rules, Rules, _cast
from . import replay, logic as L, store, community
from .findings import label_finding
from .logic import H

WARMUP = 55


def buy_hold(h1, fee, slip):
    if len(h1) < 2: return {"n": 0, "expectancy_r": 0, "win_rate": 0, "max_dd": 0, "ret": 0}
    e, x = h1[0]["close"], h1[-1]["close"]
    ret = (x * (1 - fee - slip)) / (e * (1 + fee + slip)) - 1
    return {"n": 1, "expectancy_r": ret, "win_rate": 1 if ret > 0 else 0, "max_dd": max(0, -ret), "ret": ret}


def momentum_1h(h1, rules, tp_r=4.0, atr_mult=3.0):
    from bot.indicators import atr, sma
    trades = []; i = WARMUP
    fee, slip = rules.taker_fee, rules.slippage
    while i < len(h1) - 1:
        c = h1[:i + 1]
        try:
            a = atr([x["high"] for x in c], [x["low"] for x in c], [x["close"] for x in c], 14)
            f, s = sma([x["close"] for x in c], 20), sma([x["close"] for x in c], 50)
        except Exception:
            i += 1; continue
        if not (c[-1]["close"] > f > s):
            i += 1; continue
        entry = h1[i + 1]["open"]; stop = entry - atr_mult * a
        if stop >= entry: i += 1; continue
        tp = entry + tp_r * (entry - stop); peak = entry; j = i + 1; why = None; px = None
        while j < len(h1):
            bar = h1[j]
            if bar["open"] <= stop: why, px = "STOP_GAP", bar["open"]; break
            if bar["open"] >= tp: why, px = "TAKE_PROFIT_GAP", bar["open"]; break
            if bar["low"] <= stop: why, px = "STOP", stop; break
            if bar["high"] >= tp: why, px = "TAKE_PROFIT", tp; break
            if bar["close"] < sma([x["close"] for x in h1[:j + 1]], 20):
                why, px = "MOMENTUM_END", bar["close"]; break
            peak = max(peak, bar["close"]); j += 1
        if why is None: break
        risk = entry - stop
        r_net = ((px * (1 - fee - slip)) / (entry * (1 + fee + slip)) - 1) / (risk / entry)
        trades.append({"entry_ts": h1[i + 1]["start"], "exit_ts": h1[j]["start"], "net_r": r_net, "why": why})
        i = j
    return trades


def momentum_4h(h1, rules, tp_r=4.0, atr_mult=2.0):
    h4 = resample(h1, 4)
    # map back via simulating on 4h then exits on 4h close
    from bot.indicators import atr, sma
    trades = []; i = 20
    fee, slip = rules.taker_fee, rules.slippage
    while i < len(h4) - 1:
        c = h4[:i + 1]
        try:
            a = atr([x["high"] for x in c], [x["low"] for x in c], [x["close"] for x in c], 14)
            f, s = sma([x["close"] for x in c], 20), sma([x["close"] for x in c], 50)
        except Exception:
            i += 1; continue
        if not (c[-1]["close"] > f > s):
            i += 1; continue
        entry = h4[i + 1]["open"]; stop = entry - atr_mult * a
        if stop >= entry: i += 1; continue
        tp = entry + tp_r * (entry - stop); j = i + 1; why = px = None
        while j < len(h4):
            bar = h4[j]
            if bar["low"] <= stop: why, px = "STOP", min(stop, bar["open"]); break
            if bar["high"] >= tp: why, px = "TAKE_PROFIT", max(tp, bar["open"]); break
            if bar["close"] < sma([x["close"] for x in h4[:j + 1]], 20):
                why, px = "MOMENTUM_END", bar["close"]; break
            j += 1
        if why is None: break
        risk = entry - stop
        r_net = ((px * (1 - fee - slip)) / (entry * (1 + fee + slip)) - 1) / (risk / entry)
        trades.append({"entry_ts": h4[i + 1]["start"], "exit_ts": h4[j]["start"], "net_r": r_net, "why": why})
        i = j
    return trades


def summarize(trades, split_frac=0.6):
    def s(t):
        n = len(t); rs = [x["net_r"] for x in t]
        return {"n": n, "win_rate": sum(1 for r in rs if r > 0) / n if n else 0.0,
                "expectancy_r": sum(rs) / n if n else 0.0,
                "max_dd": _dd(rs)}
    if not trades: return {"full": s([]), "oos": s([]), "in_sample": s([])}
    times = sorted(t["entry_ts"] for t in trades)
    # use span of entry times
    lo, hi = trades[0]["entry_ts"], trades[-1]["exit_ts"]
    # better: from data span passed separately — use entry order
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    cut = trades[0]["entry_ts"] + (trades[-1]["entry_ts"] - trades[0]["entry_ts"]) * split_frac
    return {"full": s(trades), "in_sample": s([t for t in trades if t["exit_ts"] < cut]),
            "oos": s([t for t in trades if t["entry_ts"] >= cut])}


def _dd(rs):
    eq = peak = 0.0; mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = max(mdd, (peak - eq) / max(1.0, abs(peak)) if peak else 0)
    # R-space DD approximate
    eq = peak = 1.0; mdd = 0.0
    for r in rs:
        eq += r * 0.01  # scale
        peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    return mdd


def run_tournament(symbols, rules, data_dir="data"):
    rows = []
    # buy-hold blended
    bh_rets = []
    for sym in symbols:
        h1 = replay.load_cached(sym, data_dir)
        bh = buy_hold(h1, rules.taker_fee, rules.slippage); bh_rets.append(bh["ret"])
    bh_avg = sum(bh_rets) / len(bh_rets) if bh_rets else 0

    specs = [
        ("01_desk_fvg_long", "desk FVG long TP4R", {"take_profit_r": 4, "no_hero": True}),
        ("04_tp2r", "desk FVG long TP2R", {"take_profit_r": 2, "no_hero": True}),
        ("05_tp4r", "desk FVG long TP4R (alias)", {"take_profit_r": 4, "no_hero": True}),
        ("06_fvg_panel_veto", "desk FVG + painel (só veto)", {"take_profit_r": 4, "no_hero": True, "panel_mode": "enforce",
                                                              "panel_neutral_mult": 1.0, "panel_vol_cap": False}),
        ("07_fvg_panel_full", "desk FVG + painel (veto+redução)", {"take_profit_r": 4, "no_hero": True, "panel_mode": "enforce"}),
        ("08_fvg_protections", "desk FVG + protections (freqtrade)", {"take_profit_r": 4, "no_hero": True, "protections_mode": "enforce"}),
    ]
    for sid, name, ov in specs:
        r = Rules({**rules.p, **ov})
        res = replay.run(symbols, r, data_dir)
        sc = replay.score(res, r)
        finding = label_finding({"n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"], "expectancy_r": sc["full"]["expectancy_r"],
                                 "max_dd": sc["max_dd"], "go": sc["go"],
                                 "thresholds": {k: (None, v) for k, v in sc["thresholds_pass"].items()}}, r, sc.get("oos"))
        rows.append({"id": sid, "name": name, "n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"],
                     "expectancy_r": sc["full"]["expectancy_r"], "max_dd": sc["max_dd"],
                     "oos_n": sc["oos"]["n"], "oos_ev": sc["oos"]["expectancy_r"], "finding": finding,
                     "vs_buyhold": sc["full"]["expectancy_r"] - bh_avg})

    # momentum strategies
    for sid, name, fn in [("02_sma_momentum", "SMA20>50 momentum 1H TP4R", momentum_1h),
                          ("03_4h_momentum_end", "4H trend + momentum-end", momentum_4h),
                          ("09_bbandrsi", "BbandRsi (freqtrade comm.) −8% stop", community.bbandrsi),
                          ("10_adxmomentum", "ADXMomentum (freqtrade comm.) −8% stop", community.adxmomentum)]:
        all_tr = []
        for sym in symbols:
            all_tr += fn(replay.load_cached(sym, data_dir), rules)
        sm = summarize(all_tr)
        fake = {"n": sm["full"]["n"], "win_rate": sm["full"]["win_rate"], "expectancy_r": sm["full"]["expectancy_r"],
                "max_dd": sm["full"]["max_dd"], "go": False,
                "thresholds": {"trades": (None, sm["full"]["n"] >= rules.threshold_trades),
                               "win_rate": (None, sm["full"]["win_rate"] >= rules.threshold_win_rate),
                               "expectancy": (None, sm["full"]["expectancy_r"] >= rules.threshold_expectancy_r),
                               "max_dd": (None, sm["full"]["max_dd"] <= rules.threshold_max_dd)}}
        finding = label_finding(fake, rules, sm["oos"])
        rows.append({"id": sid, "name": name, "n": sm["full"]["n"], "win_rate": sm["full"]["win_rate"],
                     "expectancy_r": sm["full"]["expectancy_r"], "max_dd": sm["full"]["max_dd"],
                     "oos_n": sm["oos"]["n"], "oos_ev": sm["oos"]["expectancy_r"], "finding": finding,
                     "vs_buyhold": sm["full"]["expectancy_r"] - bh_avg})

    rows.sort(key=lambda r: (r["finding"] != "DATA_VALIDATED", -r["expectancy_r"]))
    return rows, bh_avg


def write_report(rows, bh_avg, path):
    lines = ["# Tournament report (Texto 5 / Miles Deutscher — adaptado)", "",
             "Não promove automaticamente nenhuma estratégia. Live desk permanece FVG long até decisão humana.",
             f"Buy-hold médio (após fees): {bh_avg:+.3%}", "",
             "| rank | id | name | n | win | EV | maxDD | OOS n | OOS EV | vs BH | finding |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append(f"| {i} | {r['id']} | {r['name']} | {r['n']} | {r['win_rate']:.1%} | {r['expectancy_r']:+.3f}R | "
                     f"{r['max_dd']:.1%} | {r['oos_n']} | {r['oos_ev']:+.3f}R | {r['vs_buyhold']:+.3f} | **{r['finding']}** |")
    lines += ["", "## Veredito", ""]
    validated = [r for r in rows if r["finding"] == "DATA_VALIDATED"]
    if validated:
        lines.append("Estratégias DATA_VALIDATED (NÃO auto-promover): " + ", ".join(r["id"] for r in validated))
    else:
        lines.append("Nenhuma estratégia DATA_VALIDATED. Todas NO_EDGE ou TRADE_OFF. Desk live inalterado.")
    lines.append("")
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols"); ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default=None); a = ap.parse_args()
    rules = load_rules(); q = rules.quote
    if a.symbols: syms = [f"{b.strip().upper()}-{q}" for b in a.symbols.split(",")]
    else:
        syms = sorted(f[len("candles_"):-len("_60.json")] for f in os.listdir(a.data_dir)
                      if f.startswith("candles_") and f.endswith(f"-{q}_60.json"))
    rows, bh = run_tournament(syms, rules, a.data_dir)
    out = a.out or store.path("tournament_report.md")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_report(rows, bh, out)
    json.dump({"symbols": syms, "buyhold": bh, "rows": rows}, open(out.replace(".md", ".json"), "w"), indent=2)
    print(open(out).read())


if __name__ == "__main__":
    main()
