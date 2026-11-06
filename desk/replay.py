"""Replay do desk sobre o histórico em cache (data/candles_<SYM>_60.json), hora a hora, sem look-ahead.
python -m desk.replay [--symbols BTC,ETH,SOL] [--out desk/state/replay]

- 1D e 4H são reamostrados de 1H em UTC (só blocos completos); uma vela só é "vista" depois do seu fecho.
- Cadeia por fecho: diário (screener → cartographer → exit_clerk), 4H (cartographer → exit_clerk),
  1H (confirmação → risk_officer → gate, que em paper assume TAKEN → auditor, que simula o fill).
- Fill da entrada na ABERTURA da vela 1H seguinte ao alerta; stops intrabar (gap → abertura).
- O quarter-Kelly do ledger NÃO é usado no replay, porque o ledger foi calculado sobre o mesmo ano (seria look-ahead).
"""
from __future__ import annotations
import argparse, bisect, json, os
from dataclasses import asdict
from bot.variants import resample
from .rules import load_rules
from . import logic as L
from .logic import H, D
from . import panel as PANEL
from . import protections as PROT
from . import macro as MACRO
from . import allocation as ALLOC


def load_cached(sym, data_dir="data"):
    return json.load(open(os.path.join(data_dir, f"candles_{sym}_60.json")))


class Series:
    def __init__(self, h1):
        self.h1 = h1; self.h4 = resample(h1, 4); self.d1 = resample(h1, 24)
        self.h1_t = [c["start"] for c in self.h1]; self.h4_t = [c["start"] for c in self.h4]; self.d1_t = [c["start"] for c in self.d1]

    def closed(self, arr, ts, iv, now):
        """velas com start + iv <= now"""
        return arr[:bisect.bisect_right(ts, now - iv)]

    def since(self, arr, ts, t0, now, iv):
        i = bisect.bisect_left(ts, t0); j = bisect.bisect_right(ts, now - iv)
        return arr[i:j]


def run(symbols, rules, data_dir="data", equity0=None, log=None, macro_ctx=None):
    eq0 = equity0 or rules.paper_equity
    if macro_ctx is None and MACRO.mode(rules) != "off":
        macro_ctx = MACRO.load()   # cache data_ext/macro; vazia -> INSUFFICIENT_DATA (sem efeito)
    S = {s: Series(load_cached(s, data_dir)) for s in symbols}
    hours = sorted({c["start"] for s in S.values() for c in s.h1})
    watch, zones, pos, pending, trades, events, curve = {}, {}, {}, {}, [], [], []
    realized = eq0; peak_eq = eq0; max_dd = 0.0
    last_px = {}
    for st in hours:
        now = st + H
        for sym, ser in S.items():
            i = bisect.bisect_left(ser.h1_t, st)
            if i >= len(ser.h1) or ser.h1_t[i] != st: continue
            c = ser.h1[i]
            # --- entradas pendentes (fill na abertura desta vela) ---
            for pl in pending.pop(sym, []):
                fill = c["open"]
                if fill <= pl["stop"]:
                    events.append({"ts": st, "sym": sym, "event": "ENTRY_VOID", "why": "abertura <= stop"}); continue
                qty, info = L.size_trade(realized, fill, pl["stop"], pl["risk"], rules)
                pd_ = pl.get("panel")
                if pd_ is not None:
                    qty, _pnote = PANEL.apply(qty, fill, realized, pd_, rules)
                if pl.get("alloc") is not None:
                    qty = ALLOC.apply(qty, fill, realized, pl["alloc"], rules)   # só reduz (enforce)
                if qty <= 0: continue
                tp = pl.get("tp")
                p = L.Position(f"{sym}:{st}", sym, fill, pl["stop"], qty, pl["risk"], pl["add"], pl["anchor"], st,
                               peak=fill, initial_stop=pl["stop"], tp_price=tp, initial_tp=tp)
                p.panel = {k: pd_[k] for k in ("action", "score", "consensus", "size_mult")} if pd_ else None
                p.prot = pl.get("prot")
                p.macro = pl.get("macro")
                pos.setdefault(sym, []).append(p)
                events.append({"ts": st, "sym": sym, "event": "ENTRY", "entry": fill, "stop": pl["stop"], "tp": tp, "add": pl["add"], "sizing": info})
            # --- exit clerk intrabar (stop / −8%) ---
            for p in list(pos.get(sym, [])):
                ex = L.check_exit(p, c, rules)
                if ex: realized = _close(p, ex[1], ex[0], st, rules, trades, pos, realized)
                else: L.after_bar(p, c, rules)
            last_px[sym] = c["close"]
            # --- fecho diário: screener, anchor exit, stale ---
            if now % D == 0:
                d = ser.closed(ser.d1, ser.d1_t, D, now)
                if d:
                    for p in list(pos.get(sym, [])):
                        if L.daily_anchor_exit(p, d[-1]["close"]):
                            realized = _close(p, d[-1]["close"], "ANCHOR_1D_CLOSE", st, rules, trades, pos, realized)
                    fl = L.active_up_flip(d, rules)
                    w = watch.get(sym)
                    if fl and (not w or w["flip"].flip_date != fl.flip_date):
                        h4c = ser.closed(ser.h4, ser.h4_t, 4 * H, now)
                        watch[sym] = {"flip": fl, "tag": "PRIME" if L.h4_pullback(h4c) else "WATCH", "added": now}
                        zones[sym] = {}
                        events.append({"ts": now, "sym": sym, "event": "WATCH", "tag": watch[sym]["tag"], "anchor": fl.anchor_low})
                    elif not fl and w:
                        watch.pop(sym); zones.pop(sym, None)
                    elif w and now - w["added"] > rules.watchlist_max_age_days * D:
                        watch.pop(sym); zones.pop(sym, None)
            # --- fecho 4H: cartographer + stale ---
            if now % (4 * H) == 0:
                for p in pos.get(sym, []):
                    if not p.stale_flagged and L.is_stale(p, now, c["close"], rules):
                        p.stale_flagged = True; events.append({"ts": now, "sym": sym, "event": "STALE"})
                if sym in watch:
                    h4c = ser.closed(ser.h4, ser.h4_t, 4 * H, now)
                    for z in L.find_fvgs(h4c, sym, watch[sym]["flip"]):
                        zones[sym].setdefault(z.zid, z)
            # --- 1H: confirmação -> risk officer -> gate (paper: TAKEN) ---
            for z in list(zones.get(sym, {}).values()):
                if z.status in ("INVALID", "USED", "EXPIRED"): continue
                h4n = ser.since(ser.h4, ser.h4_t, z.formed_ts, now, 4 * H)
                h1n = ser.since(ser.h1, ser.h1_t, max(z.formed_ts, z.last_h1 + 1), now, H)
                L.update_zone(z, h4n, h1n, rules)
                if z.status == "CONFIRMED":
                    z.status = "USED"
                    if now - z.confirm_ts > rules.max_alert_age_hours * H:   # mesma regra do risk_officer (catch-up)
                        z.status = "EXPIRED"; events.append({"ts": now, "sym": sym, "event": "EXPIRED"}); continue
                    open_p = pos.get(sym, [])
                    add = len(open_p) + len(pending.get(sym, []))
                    if add and (add > rules.max_adds or pending.get(sym) or not all(p.at_be for p in open_p)):
                        events.append({"ts": now, "sym": sym, "event": "ADD_REJECTED", "why": "anterior não está em breakeven" if add <= rules.max_adds else "max_adds"})
                        continue
                    # no-hero in replay: only PRIME tags (matches live risk_officer)
                    if rules.no_hero and watch[sym].get("tag") != "PRIME":
                        events.append({"ts": now, "sym": sym, "event": "NO_HERO_WEAK", "tag": watch[sym].get("tag")}); continue
                    prot = None
                    if PROT.mode(rules) != "off":
                        lk = PROT.locks(trades, now, realized, rules)
                        fr = PROT.pair_filters(ser.closed(ser.d1, ser.d1_t, D, now), rules)
                        prot = PROT.blocked(sym, lk) + fr["reasons"]
                        if PROT.mode(rules) == "enforce" and prot:
                            events.append({"ts": now, "sym": sym, "event": "PROT_VETO", "why": prot}); continue
                    mdec = None
                    if MACRO.mode(rules) != "off":
                        mdec = MACRO.evaluate(macro_ctx, now, rules)
                        if MACRO.mode(rules) == "enforce" and mdec["action"] == "VETO":
                            events.append({"ts": now, "sym": sym, "event": "MACRO_VETO", "flags": mdec["flags"]}); continue
                    pdec = None
                    if rules.p.get("panel_mode", "shadow") != "off":
                        bs = S.get("BTC-" + sym.split("-")[1])
                        pdec = PANEL.evaluate(rules, ser.closed(ser.h4, ser.h4_t, 4 * H, now)[-150:], ser.closed(ser.d1, ser.d1_t, D, now)[-150:],
                                              bs.closed(bs.d1, bs.d1_t, D, now)[-150:] if bs else None,
                                              [S[o].closed(S[o].d1, S[o].d1_t, D, now)[-90:] for o in pos if o != sym])
                        if rules.p.get("panel_mode") == "enforce" and pdec["action"] == "VETO":
                            events.append({"ts": now, "sym": sym, "event": "PANEL_VETO", "score": pdec["score"]}); continue
                    adec = None
                    if ALLOC.mode(rules) != "off":
                        adec = ALLOC.decision(sym, ser.closed(ser.d1, ser.d1_t, D, now)[-91:],
                                              {o: S[o].closed(S[o].d1, S[o].d1_t, D, now)[-91:] for o in pos if o != sym}, rules)
                    tpr = float(rules.p.get("take_profit_r") or 0)
                    tp = L.tp_price(z.entry, z.stop, tpr) if tpr > 0 else None
                    pending.setdefault(sym, []).append({"stop": z.stop, "tp": tp, "risk": rules.add_risk_pct if add else rules.risk_pct,
                                                        "add": add, "anchor": watch[sym]["flip"].anchor_low, "panel": pdec, "prot": prot,
                                                        "macro": {"status": mdec["status"], "flags": mdec["flags"]} if mdec else None,
                                                        "alloc": adec})
                    events.append({"ts": now, "sym": sym, "event": "ALERT", "zone": [z.bottom, z.top], "entry_ref": z.entry,
                                   "stop": z.stop, "tp": tp, "add": add})
        # equity mark-to-market
        mtm = realized + sum(p.qty * (last_px.get(p.symbol, p.entry) - p.entry) for ps in pos.values() for p in ps)
        peak_eq = max(peak_eq, mtm); max_dd = max(max_dd, (peak_eq - mtm) / peak_eq)
        if now % D == 0: curve.append((now, mtm))
    open_n = sum(len(v) for v in pos.values())
    return {"trades": trades, "events": events, "curve": curve, "max_dd": max_dd, "open_positions": open_n,
            "equity_end": curve[-1][1] if curve else eq0, "equity0": eq0, "first": hours[0] if hours else None, "last": hours[-1] if hours else None}


def _close(p, px, why, ts, rules, trades, pos, realized):
    r = L.trade_r(p.entry, px, p.initial_stop, rules)
    pnl = p.qty * (r["fill_out"] - r["fill_in"]) - p.qty * r["fee_per_unit"]
    trades.append({"pid": p.pid, "symbol": p.symbol, "entry_ts": p.opened_ts, "exit_ts": ts, "entry": p.entry, "exit": px,
                   "stop": p.initial_stop, "qty": p.qty, "risk_frac": p.risk_frac, "add": p.add_number, "why": why,
                   "gross_r": r["gross_r"], "net_r": r["net_r"], "fee": p.qty * r["fee_per_unit"],
                   "slippage": p.qty * r["slippage_per_unit"], "pnl": pnl, "tp": p.tp_price, "panel": getattr(p, "panel", None), "prot": getattr(p, "prot", None),
                   "macro": getattr(p, "macro", None)})
    pos[p.symbol].remove(p)
    if not pos[p.symbol]: pos.pop(p.symbol)
    return realized + pnl


def score(res, rules, split_frac=0.6):
    tr = res["trades"]
    def s(t):
        n = len(t); w = sum(1 for x in t if x["net_r"] > 0); rs = sorted(x["net_r"] for x in t)
        eff = [x["qty"] * (x["entry"] - x["stop"]) for x in t]
        return {"n": n, "win_rate": w / n if n else 0.0, "expectancy_r": sum(rs) / n if n else 0.0,
                "median_r": rs[n // 2] if n else 0.0,
                "expectancy_r_ex_best": (sum(rs[:-1]) / (n - 1)) if n > 1 else 0.0,
                "best_r": rs[-1] if n else 0.0,
                "pnl_usd": sum(x["pnl"] for x in t),
                "pnl_per_planned_risk": (sum(x["pnl"] for x in t) / sum(eff)) if eff and sum(eff) > 0 else 0.0}
    full = s(tr)
    split = res["first"] + (res["last"] - res["first"]) * split_frac if tr else 0
    oos = s([t for t in tr if t["entry_ts"] >= split]); ins = s([t for t in tr if t["exit_ts"] < split])
    th = {"trades": full["n"] >= rules.threshold_trades, "win_rate": full["win_rate"] >= rules.threshold_win_rate,
          "expectancy": full["expectancy_r"] >= rules.threshold_expectancy_r, "max_dd": res["max_dd"] <= rules.threshold_max_dd}
    by_sym = {}
    for t in tr: by_sym.setdefault(t["symbol"], []).append(t)
    from .metrics import trade_metrics, curve_metrics
    metrics = {"trades_full": trade_metrics([t["net_r"] for t in tr]),
               "trades_oos": trade_metrics([t["net_r"] for t in tr if t["entry_ts"] >= split]),
               "curve": curve_metrics([v for _, v in res.get("curve", [])])}   # descritivas; não mudam o GO
    return {"full": full, "in_sample": ins, "oos": oos, "max_dd": res["max_dd"], "thresholds_pass": th, "go": all(th.values()), "metrics": metrics,
            "equity0": res["equity0"], "equity_end": res["equity_end"], "open_positions": res["open_positions"],
            "by_symbol": {k: s(v) for k, v in sorted(by_sym.items())},
            "exit_reasons": {k: sum(1 for t in tr if t["why"] == k) for k in sorted({t["why"] for t in tr})},
            "alerts": sum(1 for e in res["events"] if e["event"] == "ALERT"),
            "adds_rejected": sum(1 for e in res["events"] if e["event"] == "ADD_REJECTED"),
            "stale_flags": sum(1 for e in res["events"] if e["event"] == "STALE"),
            "panel_vetoes": sum(1 for e in res["events"] if e["event"] == "PANEL_VETO"),
            "panel_shadow": panel_shadow(tr, split),
            "prot_vetoes": sum(1 for e in res["events"] if e["event"] == "PROT_VETO"),
            "prot_veto_reasons": _reason_counts(res["events"]),
            "prot_shadow": prot_shadow(tr, split),
            "macro_vetoes": sum(1 for e in res["events"] if e["event"] == "MACRO_VETO"),
            "macro_shadow": macro_shadow(tr, split)}


def _reason_counts(events):
    c = {}
    for e in events:
        if e["event"] == "PROT_VETO":
            for w in e["why"]: k = w.split(":")[0]; c[k] = c.get(k, 0) + 1
    return c


def prot_shadow(tr, split):
    """Diagnóstico: trades que as protections TERIAM bloqueado (BLOCK) vs passado (PASS)."""
    out = {}
    for t in tr:
        pr = t.get("prot")
        a = "NONE" if pr is None else ("BLOCK" if pr else "PASS")
        for k in (("full", "oos") if t["entry_ts"] >= split else ("full",)):
            out.setdefault(a, {}).setdefault(k, []).append(t["net_r"])
    return {a: {k: {"n": len(v), "win_rate": sum(1 for x in v if x > 0) / len(v), "expectancy_r": sum(v) / len(v)}
                for k, v in d.items()} for a, d in out.items()}


def macro_shadow(tr, split):
    """Diagnóstico: stats por estado macro no momento do alerta (OK/CAUTION/RISK_OFF/INSUFFICIENT_DATA)."""
    out = {}
    for t in tr:
        a = (t.get("macro") or {}).get("status", "NONE")
        for k in ("full", "oos") if t["entry_ts"] >= split else ("full",):
            out.setdefault(a, {}).setdefault(k, []).append(t["net_r"])
    return {a: {k: {"n": len(v), "win_rate": sum(1 for x in v if x > 0) / len(v), "expectancy_r": sum(v) / len(v)}
                for k, v in d.items()} for a, d in out.items()}


def panel_shadow(tr, split):
    """Diagnóstico: stats por ação do painel (o que o painel TERIA feito), full e OOS."""
    out = {}
    for t in tr:
        a = (t.get("panel") or {}).get("action", "NONE")
        for k in ("full", "oos") if t["entry_ts"] >= split else ("full",):
            d = out.setdefault(a, {}).setdefault(k, [])
            d.append(t["net_r"])
    return {a: {k: {"n": len(v), "win_rate": sum(1 for x in v if x > 0) / len(v), "expectancy_r": sum(v) / len(v)}
                for k, v in d.items()} for a, d in out.items()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols"); ap.add_argument("--quote", default=None)
    ap.add_argument("--out", default="desk/state/replay"); ap.add_argument("--data-dir", default="data")
    ap.add_argument("--set", action="append", default=[], help="sensibilidade (NÃO altera DESK_RULES.md): chave=valor")
    a = ap.parse_args(); rules = load_rules(); q = a.quote or rules.quote
    if a.set:
        from .rules import Rules, _cast
        rules = Rules({**rules.p, **{k: _cast(v) for k, v in (x.split("=", 1) for x in a.set)}})
    if a.symbols: syms = [f"{b.strip().upper()}-{q}" for b in a.symbols.split(",")]
    else: syms = sorted(f[len("candles_"):-len("_60.json")] for f in os.listdir(a.data_dir) if f.startswith("candles_") and f.endswith(f"-{q}_60.json"))
    res = run(syms, rules, a.data_dir); sc = score(res, rules)
    from .findings import label_finding
    finding = label_finding({"n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"], "expectancy_r": sc["full"]["expectancy_r"],
                             "max_dd": sc["max_dd"], "go": sc["go"],
                             "thresholds": {k: (None, v) for k, v in sc["thresholds_pass"].items()}}, rules, sc.get("oos"))
    sc["finding"] = finding
    os.makedirs(a.out, exist_ok=True)
    json.dump({"symbols": syms, "overrides": a.set, "score": sc, "trades": res["trades"]}, open(os.path.join(a.out, "replay_results.json"), "w"), indent=2, default=str)
    print(json.dumps({"symbols": syms, "finding": finding, **sc}, indent=2, default=str))


if __name__ == "__main__":
    main()
