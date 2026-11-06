"""Recolha de dados PÚBLICOS da Revolut X (sem credenciais): fita de trades (`/api/1.0/public/trades/all`)
e snapshots do order book (`/api/2.0/public/order-book/{symbol}`). Respeita 1 req/s TOTAL (um único limitador).
python -m desk.revx_tape collect --symbols BTC,ETH,SOL,DOGE --days 21 --out data_tape
Retoma: dias já completos (ficheiro .done) são saltados. Só GET públicos.
"""
from __future__ import annotations
import argparse, json, os, time
from bot.revolutx import RevolutXClient
from bot.revolutx.client import BASE_HOST

D = 86_400_000


class Public:
    def __init__(self):
        self.c = RevolutXClient()          # sem api_key/private_key -> só endpoints públicos funcionam

    def trades(self, symbol, start, end, cursor=None):
        p = {"symbol": symbol, "limit": 100, "start_date": start, "end_date": end}
        if cursor: p["cursor"] = cursor
        return self.c._request("GET", "/public/trades/all", p, auth=False)

    def order_book(self, symbol, limit=20):
        self.c.rl_public.acquire(self.c.sleep)
        r = self.c.s.get(f"{BASE_HOST}/api/2.0/public/order-book/{symbol}", params={"limit": limit}, timeout=15)
        r.raise_for_status(); return r.json()


def book_stats(ob):
    """Spread relativo e profundidade a 10 bps de cada lado (quote)."""
    d = ob.get("data", ob); bids, asks = d.get("bids") or [], d.get("asks") or []
    if not bids or not asks: return None
    bb, ba = float(bids[0]["price"]), float(asks[0]["price"]); mid = (bb + ba) / 2
    dep = lambda lv, side: sum(float(x["price"]) * float(x["quantity"]) for x in lv
                               if abs(float(x["price"]) / mid - 1) <= 0.001)
    return {"bid": bb, "ask": ba, "mid": mid, "spread_bps": (ba - bb) / mid * 1e4,
            "depth10_bid": dep(bids, "b"), "depth10_ask": dep(asks, "a"), "bid_qty": float(bids[0]["quantity"]), "ask_qty": float(asks[0]["quantity"])}


def collect(symbols, days, out, until=None, ob_every=30, log=print):
    api = Public(); os.makedirs(out, exist_ok=True)
    until = until or (int(time.time() * 1000) // D * D)
    obf = open(os.path.join(out, "orderbook_samples.jsonl"), "a"); calls = 0
    for s in symbols:
        for k in range(days, 0, -1):
            a = until - k * D; b = a + D
            fn = os.path.join(out, f"{s}_{a}.jsonl")
            if os.path.exists(fn + ".done"): continue
            rows, cur = [], None
            while True:
                r = api.trades(s, a, b, cur); calls += 1
                rows += r.get("data") or []; cur = (r.get("metadata") or {}).get("next_cursor")
                if calls % ob_every == 0:
                    for so in symbols[:3]:
                        try:
                            st = book_stats(api.order_book(so))
                            if st: obf.write(json.dumps({"ts": int(time.time() * 1000), "symbol": so, **st}) + "\n"); obf.flush()
                        except Exception as e:
                            log(f"ob {so}: {type(e).__name__}")
                if not cur or not r.get("data"): break
            with open(fn, "w") as f:
                for t in sorted({t["id"]: t for t in rows}.values(), key=lambda t: t["timestamp"]):
                    f.write(json.dumps({"ts": int(t["timestamp"]), "px": float(t["price"]), "qty": float(t["quantity"]),
                                        "side": t.get("side"), "region": t.get("region")}) + "\n")
            open(fn + ".done", "w").close()
            log(f"{s} {time.strftime('%Y-%m-%d', time.gmtime(a / 1000))}: {len(rows)} trades ({calls} pedidos)")
    json.dump({"symbols": symbols, "days": days, "until": until}, open(os.path.join(out, "manifest.json"), "w"))


def load(out, symbol):
    rows = []
    for fn in sorted(os.listdir(out)):
        if fn.startswith(symbol + "_") and fn.endswith(".jsonl"):
            rows += [json.loads(l) for l in open(os.path.join(out, fn)) if l.strip()]
    return sorted(rows, key=lambda t: t["ts"])


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--symbols", required=True); c.add_argument("--days", type=int, default=21)
    c.add_argument("--out", default="data_tape"); c.add_argument("--until", type=int, default=None)
    a = ap.parse_args()
    collect([f"{x.strip().upper()}-USD" for x in a.symbols.split(",")], a.days, a.out, a.until)


if __name__ == "__main__":
    main()
