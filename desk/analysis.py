"""Rigor de backtest (ideias de freqtrade lookahead-analysis / recursive-analysis, re-implementadas).
python -m desk.analysis [--symbols BTC,ETH,SOL] [--set chave=valor]

- lookahead: corre o replay sobre dados truncados em vários cortes; tudo o que aconteceu ANTES do corte
  (eventos e trades fechados) tem de ser idêntico ao replay completo. Diferença ⇒ o replay usa dados futuros.
- recursive: o painel usa indicadores recursivos (EMA/ADX/Wilder). Compara a decisão com 150 vs 400 velas de
  histórico em vários instantes; mede a sensibilidade ao tamanho do arranque.
"""
from __future__ import annotations
import argparse, json, os, tempfile
from .rules import load_rules, Rules, _cast
from . import replay, panel as PANEL
from .logic import H, D


def _key_ev(e): return json.dumps(e, sort_keys=True, default=str)


def lookahead(symbols, rules, data_dir="data", cuts=(0.3, 0.5, 0.7, 0.9)):
    full = replay.run(symbols, rules, data_dir)
    data = {s: replay.load_cached(s, data_dir) for s in symbols}
    t0 = min(c["start"] for v in data.values() for c in v); t1 = max(c["start"] for v in data.values() for c in v)
    out = []
    for f in cuts:
        cut = int(t0 + (t1 - t0) * f) // H * H
        with tempfile.TemporaryDirectory() as d:
            for s, v in data.items():
                json.dump([c for c in v if c["start"] < cut], open(os.path.join(d, f"candles_{s}_60.json"), "w"))
            part = replay.run(symbols, rules, d)
        # o run parcial processa horas com start < cut (now ≤ cut)
        a = [_key_ev(e) for e in full["events"] if e["ts"] < cut]
        b = [_key_ev(e) for e in part["events"] if e["ts"] < cut]
        ta = [_key_ev(t) for t in full["trades"] if t["exit_ts"] < cut - H]
        tb = [_key_ev(t) for t in part["trades"] if t["exit_ts"] < cut - H]
        out.append({"cut_frac": f, "events_before_cut": len(a), "events_equal": a == b, "trades_before_cut": len(ta), "trades_equal": ta == tb})
    return {"ok": all(x["events_equal"] and x["trades_equal"] for x in out), "cuts": out}


def recursive(symbols, rules, data_dir="data", short=150, long=400, samples=20):
    from bot.variants import resample
    rows = []
    btc = next((s for s in symbols if s.startswith("BTC-")), None)
    bd1 = resample(replay.load_cached(btc, data_dir), 24) if btc else None
    for s in symbols:
        h1 = replay.load_cached(s, data_dir); h4, d1 = resample(h1, 4), resample(h1, 24)
        idx = [int(len(d1) * (0.5 + 0.5 * k / samples)) for k in range(samples)]
        for di in idx:
            if di < long // 6 + 1: continue
            now = d1[di - 1]["start"] + D
            h4c = [c for c in h4 if c["start"] + 4 * H <= now]; d1c = d1[:di]
            b = [c for c in bd1 if c["start"] + D <= now] if bd1 else None
            A = PANEL.evaluate(rules, h4c[-short:], d1c[-short:], b[-short:] if b else None)
            B = PANEL.evaluate(rules, h4c[-long:], d1c[-long:], b[-long:] if b else None)
            rows.append({"sym": s, "ts": now, "d_score": abs(A["score"] - B["score"]), "same_action": A["action"] == B["action"]})
    n = len(rows)
    return {"samples": n, "action_agreement": (sum(r["same_action"] for r in rows) / n) if n else None,
            "max_score_diff": max((r["d_score"] for r in rows), default=None),
            "mean_score_diff": (sum(r["d_score"] for r in rows) / n) if n else None}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols"); ap.add_argument("--data-dir", default="data")
    ap.add_argument("--set", action="append", default=[]); ap.add_argument("--out", default="desk/state/analysis_report.json")
    a = ap.parse_args(); rules = load_rules(); q = rules.quote
    if a.set: rules = Rules({**rules.p, **{k: _cast(v) for k, v in (x.split("=", 1) for x in a.set)}})
    syms = ([f"{b.strip().upper()}-{q}" for b in a.symbols.split(",")] if a.symbols else
            sorted(f[len("candles_"):-len("_60.json")] for f in os.listdir(a.data_dir) if f.startswith("candles_") and f.endswith(f"-{q}_60.json")))
    rep = {"symbols": syms, "overrides": a.set, "lookahead": lookahead(syms, rules, a.data_dir), "recursive": recursive(syms, rules, a.data_dir)}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True); json.dump(rep, open(a.out, "w"), indent=2)
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
