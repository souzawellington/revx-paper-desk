"""Regime ACTUAL a partir de dados reais e públicos (sem credenciais):
  Revolut X /public/candles 1D (preço/tendência/vol/amplitude) + /public/order-book (spread/profundidade),
  OKX /public/funding-rate-history e /public/open-interest (só como DADO; derivados não são negociáveis por retalho UK),
  desk.macro.live_decision (VIX/DXY/10y via yfinance).
Respeita 1 req/s na Revolut X; erros 5xx/timeout → retry com backoff e, se persistirem, o campo fica INSUFFICIENT_DATA.
python -m desk.research.regime  → desk/state/estudo_estrategias/regime.json
"""
from __future__ import annotations
import json, math, os, time
import numpy as np
import requests

RX = "https://revx.revolut.com/api/1.0"
OKX = "https://www.okx.com/api/v5/public"
SYMS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "DOT", "LTC", "BCH", "UNI", "AAVE", "NEAR", "SUI"]
OUT = "desk/state/estudo_estrategias/regime.json"


def get(url, params=None, tries=4, pause=1.05):
    for k in range(tries):
        time.sleep(pause)
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200: return r.json()
            if r.status_code < 500 and r.status_code != 429: return None
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    return None


def sma(x, n): return float(np.mean(x[-n:])) if len(x) >= n else float("nan")


def asset_stats(c):
    lr = np.diff(np.log(c)); out = {"close": float(c[-1])}
    for n in (50, 100, 200): out[f"above_sma{n}"] = bool(c[-1] > sma(c, n)) if len(c) >= n else None
    for n in (30, 60, 90): out[f"ret{n}d"] = float(c[-1] / c[-1 - n] - 1) if len(c) > n else None
    out["rv30_ann"] = float(np.std(lr[-30:]) * math.sqrt(365)) if len(lr) >= 30 else None
    if len(lr) >= 365:
        roll = np.array([np.std(lr[i - 30:i]) for i in range(30, len(lr) + 1)]) * math.sqrt(365)
        out["rv30_pctile_hist"] = float((roll <= out["rv30_ann"]).mean())
    out["dd_from_1y_high"] = float(c[-1] / np.max(c[-365:]) - 1)
    return out


def book(sym):
    j = get(f"{RX}/public/order-book/{sym}-USD")
    if not j: return None
    d = j.get("data", j); b, a = d.get("bids") or [], d.get("asks") or []
    if not b or not a: return None
    bb, ba = float(b[0]["p"]), float(a[0]["p"]); mid = (bb + ba) / 2
    dep = lambda lv: sum(float(x["p"]) * float(x["q"]) for x in lv if abs(float(x["p"]) / mid - 1) <= 0.005)
    return {"spread_bps": (ba - bb) / mid * 1e4, "depth_0.5pct_bid_usd": dep(b), "depth_0.5pct_ask_usd": dep(a)}


def funding(inst):
    j = get(f"{OKX}/funding-rate-history", {"instId": inst, "limit": 100}, pause=0.2)
    oi = get(f"{OKX}/open-interest", {"instId": inst}, pause=0.2)
    if not j or not j.get("data"): return None
    fr = np.array([float(x["fundingRate"]) for x in j["data"]])
    return {"funding_last": float(fr[0]), "funding_mean_last_n": float(fr.mean()), "n": int(len(fr)),
            "funding_annualised_mean": float(fr.mean() * 3 * 365),
            "oi_usd": float(oi["data"][0]["oiUsd"]) if oi and oi.get("data") else None}


def main():
    now = int(time.time() * 1000); rep = {"asof_ms": now, "assets": {}, "errors": []}
    closes = {}
    for s in SYMS:
        j = get(f"{RX}/public/candles/{s}-USD", {"interval": 1440})
        if not j or not j.get("data"): rep["errors"].append(f"candles {s}"); continue
        rows = sorted(j["data"], key=lambda r: int(r["start"]))
        rows = [r for r in rows if int(r["start"]) + 86_400_000 <= now]          # só velas fechadas
        c = np.array([float(r["close"]) for r in rows]); closes[s] = c
        rep["assets"][s] = {**asset_stats(c), "bars": len(c), "last_day_ms": int(rows[-1]["start"])}
    A = rep["assets"]
    def frac(k): v = [x[k] for x in A.values() if x.get(k) is not None]; return float(np.mean([bool(x) if isinstance(x, bool) else x > 0 for x in v])) if v else None
    rep["breadth"] = {"frac_ret60_pos": frac("ret60d"), "frac_above_sma100": frac("above_sma100"), "frac_above_sma200": frac("above_sma200"), "n": len(A)}
    rep["books"] = {s: book(s) for s in ("BTC", "ETH", "SOL")}
    rep["funding_oi_okx"] = {i: funding(i) for i in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")}
    try:
        from desk.macro import live_decision
        from desk.rules import load_rules
        rep["macro"] = live_decision(load_rules(), refresh=True, log=lambda *a: None)
    except Exception as e:
        rep["macro"] = {"status": "INSUFFICIENT_DATA", "error": str(e)[:200]}
    # sinais de hoje dos campeões que só precisam de BTC/ETH (C3) — dados Revolut X
    sig = {}
    for s in ("BTC", "ETH"):
        c = closes.get(s)
        if c is None or len(c) < 101: continue
        rv = float(np.std(np.diff(np.log(c[-31:]))) * math.sqrt(365))
        sig[s] = {"above_sma100": bool(c[-1] > sma(c, 100)), "w_voltarget_0.5": round(0.5 * min(1.0, 0.5 / rv), 4) if c[-1] > sma(c, 100) else 0.0}
    rep["c3_signal_today"] = sig
    b = A.get("BTC", {})
    trend = "ALTA" if b.get("above_sma200") and b.get("above_sma100") else ("BAIXA" if b.get("above_sma200") is False and b.get("above_sma100") is False else "MISTO/TRANSIÇÃO")
    volr = b.get("rv30_pctile_hist"); vol = None if volr is None else ("ALTA" if volr > 0.75 else "BAIXA" if volr < 0.25 else "NORMAL")
    rep["label"] = {"tendencia_btc": trend, "volatilidade_btc": vol, "amplitude": rep["breadth"]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True); json.dump(rep, open(OUT, "w"), indent=1, default=str)
    print(json.dumps({k: rep[k] for k in ("label", "c3_signal_today", "books", "funding_oi_okx", "errors")}, indent=1, default=str))
    print(json.dumps({s: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for s, x in A.items()}, default=str)[:3000])
    print(json.dumps(rep.get("macro"), default=str)[:800])


if __name__ == "__main__":
    main()
