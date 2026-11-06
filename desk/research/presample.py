"""Teste pré-amostra da spec 15 (TSMOM 60d) em Coinbase 1D 2020-10-20 → 2023-10-19, via CCXT PÚBLICO (sem credenciais).
python -m desk.research.presample [--refresh]"""
from __future__ import annotations
import argparse, json, os
import numpy as np
from . import sweep as S

P0, P1 = 1603152000000, 1697673600000      # 2020-10-20, 2023-10-19 (exclusivo)
OUT_DIR = "data_ext/coinbase_1d_presample"


def fetch(log=print):
    from desk.ccxt_data import PublicOnly
    ex = PublicOnly("coinbase"); ex.load_markets(); os.makedirs(OUT_DIR, exist_ok=True)
    for s in S.SYMS:
        sym = f"{s}/USD"
        if sym not in ex.markets: log(f"{sym}: não listado"); continue
        rows, cur = {}, P0 - 70 * S.D                    # 70 dias de aquecimento para o lookback 60
        while cur < P1:
            b = ex.fetch_ohlcv(sym, "1d", since=cur, limit=300)
            if not b: cur += 300 * S.D; continue
            for t, o, h, l, c, v in b:
                if t + S.D <= P1: rows[int(t)] = {"start": int(t), "open": o, "high": h, "low": l, "close": c, "volume": v or 0}
            nxt = int(b[-1][0]) + S.D
            if nxt <= cur: break
            cur = nxt
        json.dump([rows[k] for k in sorted(rows)], open(os.path.join(OUT_DIR, f"candles_{s}-USD_60.json"), "w"))
        log(f"{sym}: {len(rows)} velas 1D")


def main():
    from desk.rules import load_rules
    ap = argparse.ArgumentParser(); ap.add_argument("--refresh", action="store_true"); a = ap.parse_args(); rules = load_rules()
    if a.refresh or not os.path.isdir(OUT_DIR): fetch()
    data = {s: d for s, d in ((s, S.load(OUT_DIR, s)) for s in S.SYMS) if d is not None and len(d["open"]) > 70}
    cfg = next(c for c in S.configs() if c["id"] == "tsmom_60_24h")
    x, tr = S.run_config(data, cfg, P0, P1); bh = S.buy_hold(data, P0, P1)
    ts = S.trade_stats(tr); aud = S.auditor(ts, S.max_dd(x), rules)
    by_year = {}
    for y0 in (P0, P0 + 365 * S.D, P0 + 730 * S.D):
        m = slice((y0 - P0) // S.D, (y0 - P0) // S.D + 365)
        tt = [t for t in tr if y0 <= t["entry_ts"] < y0 + 365 * S.D]
        by_year[f"ano_{(y0 - P0) // (365 * S.D) + 1}"] = {"ret": float(np.prod(1 + x[m]) - 1), "sharpe": S.sharpe(x[m]), **S.trade_stats(tt)}
    res = {"pairs": sorted(data), "sharpe": S.sharpe(x), "ret": float(np.prod(1 + x) - 1), "max_dd": S.max_dd(x), **ts, "auditor": aud,
           "bh": {"sharpe": S.sharpe(bh), "ret": float(np.prod(1 + bh) - 1), "max_dd": S.max_dd(bh)}, "by_year": by_year,
           "finding": "DATA_VALIDATED" if all(aud.values()) else ("TRADE_OFF" if ts["n"] >= rules.threshold_trades else "NO_EDGE")}
    json.dump(res, open("desk/state/research_presample.json", "w"), indent=1, default=float); print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
