"""Klines 1m PÚBLICOS de data.binance.vision (sem chave; só HTTP GET de ZIPs) → data_ext/binance_vision/1m/<SYM>.npz
Pares USDT como PROXY dos pares USD da Revolut X (BTC, ETH, SOL, XRP, DOGE, ADA — todos listados na Revolut X).
python -m desk.research.scalp_data [--symbols BTC,ETH] [--start 2024-09 --end 2026-09]
"""
from __future__ import annotations
import argparse, json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from desk.research.binance_vision import BASE, get, months, parse_zip

OUT = "data_ext/binance_vision/1m"
SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"]


def fetch(sym, start="2024-09", end="2026-09"):
    pair = f"{sym}USDT"; y0, m0 = map(int, start.split("-")); y1, m1 = map(int, end.split("-"))
    yms = list(months(y0, m0, y1, m1))
    urls = [f"{BASE}/{pair}/1m/{pair}-1m-{ym}.zip" for ym in yms]
    with ThreadPoolExecutor(6) as ex: blobs = list(ex.map(get, urls))
    rows = {}; missing = [ym for ym, b in zip(yms, blobs) if not b]
    for b in blobs:
        if b:
            for r in parse_zip(b): rows[r["start"]] = r
    ks = sorted(rows)
    arr = {"ts": np.array(ks, np.int64)}
    for k, f in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"), ("qv", "quote_volume")):
        arr[k] = np.array([rows[t][f] for t in ks], np.float64)
    return arr, missing


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols", default=",".join(SYMS))
    ap.add_argument("--start", default="2024-09"); ap.add_argument("--end", default="2026-09"); a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True); man = {}
    for s in [x.strip().upper() for x in a.symbols.split(",") if x.strip()]:
        arr, miss = fetch(s, a.start, a.end)
        np.savez_compressed(os.path.join(OUT, f"{s}.npz"), **arr)
        man[s] = {"bars": int(len(arr["ts"])), "first": int(arr["ts"][0]) if len(arr["ts"]) else None,
                  "last": int(arr["ts"][-1]) if len(arr["ts"]) else None, "missing_months": miss}
        print(s, man[s], flush=True)
    json.dump({"source": "data.binance.vision (público)", "quote": "USDT (proxy de USD na Revolut X)", "start": a.start, "end": a.end,
               "symbols": man}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
