"""Exporta "intenções de trade" (entrada, stop, TP, saída forçada) das specs do desk para verificação externa
(ex. NautilusTrader, ver tools/nautilus_harness.py). Só dados; nada aqui fala com exchanges.
python -m desk.intents --spec 01|09|10|03 --data-dir data_ext/coinbase --symbols BTC,ETH,SOL --out /tmp/intents_01.json
"""
from __future__ import annotations
import argparse, json, os
from .rules import load_rules, Rules
from . import replay, community
from .logic import H

STOPLIKE = ("STOP", "STOP_GAP", "HARD_STOP_8PCT", "HARD_STOP_8PCT_GAP", "TAKE_PROFIT", "TAKE_PROFIT_GAP", "ROI")


def from_replay(symbols, rules, data_dir):
    res = replay.run(symbols, rules, data_dir); out = []
    for t in res["trades"]:
        forced = None if t["why"] in STOPLIKE else t["exit_ts"]
        tp = t.get("tp")
        out.append({"symbol": t["symbol"], "entry_ts": t["entry_ts"], "stop_abs": t["stop"], "tp_abs": tp, "stop_pct": None,
                    "tp_pct": None, "forced_exit_ts": forced, "trail_hard_pct": rules.hard_stop_pct,
                    "be_trigger_r": rules.be_trigger_r if rules.p.get("be_move_stop", True) else None,
                    "ref_net_r": t["net_r"], "ref_why": t["why"], "ref_entry": t["entry"], "ref_exit": t["exit"]})
    return out


def from_community(symbols, rules, data_dir, fn, roi):
    out = []
    for s in symbols:
        for t in fn(replay.load_cached(s, data_dir), rules):
            forced = t["exit_ts"] if t["why"] == "EXIT_SIGNAL" else None
            out.append({"symbol": s, "entry_ts": t["entry_ts"], "stop_abs": None, "tp_abs": None, "stop_pct": community.HARD,
                        "tp_pct": roi, "forced_exit_ts": forced, "trail_hard_pct": None, "be_trigger_r": None,
                        "ref_net_r": t["net_r"], "ref_why": t["why"]})
    return out


def build(spec, symbols, rules, data_dir):
    if spec == "01": return from_replay(symbols, Rules({**rules.p, "take_profit_r": 4, "no_hero": True}), data_dir)
    if spec == "09": return from_community(symbols, rules, data_dir, community.bbandrsi, 0.10)
    if spec == "10": return from_community(symbols, rules, data_dir, community.adxmomentum, 0.01)
    raise SystemExit(f"spec {spec} não suportada")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--spec", required=True); ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", default="BTC,ETH,SOL"); ap.add_argument("--out", required=True)
    a = ap.parse_args(); rules = load_rules()
    syms = [f"{b.strip().upper()}-{rules.quote}" for b in a.symbols.split(",")]
    it = build(a.spec, syms, rules, a.data_dir)
    json.dump({"spec": a.spec, "data_dir": a.data_dir, "symbols": syms, "taker_fee": rules.taker_fee, "slippage": rules.slippage,
               "intents": it}, open(a.out, "w"))
    print(f"{len(it)} intents -> {a.out}")


if __name__ == "__main__":
    main()
