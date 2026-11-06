"""Papel 1 — SCREENER. Dono: encontrar moedas cujo 1D virou para ALTA (DESK_RULES.md).
Saída: watchlist.csv (coin, anchor_low, flip_date, tag). Pára na watchlist: não mapeia zonas, não dimensiona."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from .rules import load_rules
from . import logic as L, market, store


def run(rules=None, symbols=None, now=None, client=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    syms = symbols or market.universe(rules, client)
    rows, ctx = [], []
    for i, s in enumerate(syms):
        try:
            d = market.candles(s, 1440, 40, now, client)
        except Exception as e:
            ctx.append({"ts": store.iso(now), "coin": s, "event": "DATA_ERROR", "note": str(e)[:120]}); continue
        fl = L.active_up_flip(d, rules)
        if fl:
            h4 = market.candles(s, 240, 6, now, client)
            tag = "PRIME" if L.h4_pullback(h4) else "WATCH"
            rows.append({"coin": s, "anchor_low": fl.anchor_low, "flip_date": store.iso(fl.flip_date)[:10], "tag": tag})
        dn = L.recent_down_flip(d, rules)
        if dn:  # contexto apenas — nunca passa adiante
            ctx.append({"ts": store.iso(now), "coin": s, "event": "BEARISH_FLIP", "flip_date": store.iso(dn)[:10], "note": "context only"})
        if (i + 1) % 50 == 0: log(f"  screener: {i + 1}/{len(syms)}")
    store.write("watchlist.csv", rows)
    store.append("context.csv", ctx)
    log(f"screener: {len(rows)} na watchlist ({sum(r['tag'] == 'PRIME' for r in rows)} PRIME), {len(syms)} pares analisados")
    return rows


def flip_from_row(r) -> L.Flip:
    fd = int(datetime.strptime(r["flip_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    return L.Flip(float(r["anchor_low"]), fd - 2 * L.D, fd, fd + L.D)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols"); a = ap.parse_args()
    rules = load_rules()
    run(rules, [f"{x.strip().upper()}-{rules.quote}" for x in a.symbols.split(",")] if a.symbols else None)


if __name__ == "__main__":
    main()
