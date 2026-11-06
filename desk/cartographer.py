"""Papel 2 — CARTOGRAPHER. Dono: mapa de zonas (FVGs 4H do impulso âncora->máxima), testes e confirmação 1H.
Saída: zones.csv. Pára no mapa: não calcula tamanho nem envia alertas."""
from __future__ import annotations
import argparse
from .rules import load_rules
from . import logic as L, market, store
from .screener import flip_from_row

NUM = ("zone_top", "zone_bottom", "test_low", "entry", "stop", "anchor_low")
INT = ("formed_ts", "tested_ts", "confirm_ts", "last_h1", "last_h4")


def row_to_zone(r) -> L.Zone:
    z = L.Zone(r["zone_id"], float(r["zone_top"]), float(r["zone_bottom"]), int(r["formed_ts"]), r["status"])
    z.confirmed = r.get("confirmed") == "True"
    for k in ("tested_ts", "confirm_ts", "last_h1", "last_h4"):
        v = r.get(k); setattr(z, k, int(v) if v not in ("", None) else (-1 if k.startswith("last") else None))
    for k in ("test_low", "entry", "stop"): setattr(z, k, store.f(r.get(k)))
    return z


def zone_to_row(coin, z: L.Zone, anchor, rank):
    return {"coin": coin, "zone_id": z.zid, "rank": rank, "zone_top": z.top, "zone_bottom": z.bottom, "status": z.status,
            "confirmed": z.confirmed, "formed_ts": z.formed_ts, "tested_ts": z.tested_ts or "", "test_low": z.test_low or "",
            "entry": z.entry or "", "stop": z.stop or "", "confirm_ts": z.confirm_ts or "", "last_h1": z.last_h1,
            "last_h4": z.last_h4, "anchor_low": anchor}


def run(confirm_only=False, rules=None, now=None, client=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    watch = {r["coin"]: r for r in store.read("watchlist.csv")}
    old = store.read("zones.csv")
    by_coin = {}
    for r in old: by_coin.setdefault(r["coin"], {})[r["zone_id"]] = r
    out = []
    for coin, zs in by_coin.items():   # zonas de moedas que saíram da watchlist
        if coin not in watch:
            for r in zs.values():
                if r["status"] in ("UNTESTED", "TESTED"): r["status"] = "DROPPED"
                out.append(r)
    for coin, w in watch.items():
        fl = flip_from_row(w)
        h4 = market.candles(coin, 240, 0, now, client, since=fl.c1_start)
        zones = {zid: row_to_zone(r) for zid, r in by_coin.get(coin, {}).items()}
        if not confirm_only or not zones:
            for z in L.find_fvgs(h4, coin, fl):
                zones.setdefault(z.zid, z)
        live = [z for z in zones.values() if z.status in ("UNTESTED", "TESTED")]
        if live:
            t0 = min((z.last_h1 + 1) if z.last_h1 > 0 else z.formed_ts for z in live)
            h1 = market.candles(coin, 60, 0, now, client, since=t0)
            for z in live: L.update_zone(z, h4, h1, rules)
        for rank, z in enumerate(sorted(zones.values(), key=lambda z: -z.top), 1):
            out.append(zone_to_row(coin, z, fl.anchor_low, rank))
    store.write("zones.csv", out)
    log(f"cartographer{' (confirm)' if confirm_only else ''}: {len(out)} zonas, "
        f"{sum(r['status'] == 'TESTED' for r in out)} testadas, {sum(r['status'] == 'CONFIRMED' for r in out)} confirmadas (por planear)")
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--confirm", action="store_true"); a = ap.parse_args()
    run(confirm_only=a.confirm)


if __name__ == "__main__":
    main()
