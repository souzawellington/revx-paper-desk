"""Adaptador CCXT (MIT) SÓ DE DADOS PÚBLICOS — dependência OPCIONAL (`pip install ccxt`).
python -m desk.ccxt_data fetch --venue coinbase --symbols BTC,ETH --days 1095 --out data_ext/coinbase
python -m desk.ccxt_data sanity --symbols BTC,ETH            (Revolut X mid vs outras venues)

Garantias (testadas):
- Nunca passa apiKey/secret/password/uid/privateKey; recusa config com credenciais e recusa se o objecto CCXT tiver credenciais.
- Expõe só load_markets / fetch_ohlcv / fetch_ticker. Qualquer outro método (create_order, fetch_balance, …) não existe no wrapper.
- enableRateLimit=True sempre (respeita o rateLimit da venue) + pausa mínima configurável.
- Não é caminho de execução: o desk nunca importa este módulo nos papéis live excepto para o sanity check público (opcional, shadow).
"""
from __future__ import annotations
import argparse, json, os, time

CRED_KEYS = ("apiKey", "secret", "password", "uid", "privateKey", "walletAddress", "token", "login", "twofa")
ALLOWED = ("load_markets", "fetch_ohlcv", "fetch_ticker", "markets")   # markets = dict público já carregado
H = 3_600_000


class PublicOnly:
    """Wrapper mínimo sobre uma instância ccxt sem credenciais."""
    def __init__(self, venue: str, config: dict | None = None, ccxt_mod=None):
        config = dict(config or {})
        bad = [k for k in CRED_KEYS if config.get(k)]
        if bad: raise ValueError(f"PublicOnly recusa credenciais: {bad}")
        if ccxt_mod is None:
            import ccxt as ccxt_mod   # opcional
        self._ex = getattr(ccxt_mod, venue)({**config, "enableRateLimit": True})
        for k in CRED_KEYS:
            if getattr(self._ex, k, None): raise ValueError(f"instância {venue} tem credencial {k}; abortado")
        self.venue = venue

    def __getattr__(self, name):
        if name in ALLOWED: return getattr(self._ex, name)
        raise AttributeError(f"PublicOnly: método '{name}' não permitido (só {ALLOWED})")

    @property
    def rate_limit_ms(self): return getattr(self._ex, "rateLimit", 1000)


def venue_symbol(base, quote="USD", venue="coinbase"):
    return f"{base}/{'USDT' if venue in ('binance', 'bybit', 'okx') and quote == 'USD' else quote}"


def fetch_hourly(ex: PublicOnly, symbol: str, since_ms: int, until_ms: int, page=300, min_sleep=0.0, log=print):
    """Paginação para a frente; só velas FECHADAS (start + 1h <= until). Deduplica por start."""
    rows, cur, calls = {}, since_ms, 0
    while cur < until_ms:
        batch = ex.fetch_ohlcv(symbol, "1h", since=cur, limit=page); calls += 1
        if not batch: 
            cur += page * H; continue   # buraco (par ainda não listado)
        for t, o, h, l, c, v in batch:
            if t + H <= until_ms: rows[int(t)] = {"start": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v or 0)}
        nxt = int(batch[-1][0]) + H
        if nxt <= cur: break
        cur = nxt
        if min_sleep: time.sleep(min_sleep)
    out = [rows[k] for k in sorted(rows)]
    log(f"{ex.venue} {symbol}: {len(out)} velas 1H em {calls} pedidos")
    return out


def quality(rows):
    """Relatório de qualidade: buracos, velas inválidas, duplicados."""
    gaps = sum(1 for a, b in zip(rows[:-1], rows[1:]) if b["start"] - a["start"] != H)
    missing = sum((b["start"] - a["start"]) // H - 1 for a, b in zip(rows[:-1], rows[1:]) if b["start"] - a["start"] > H)
    bad = sum(1 for r in rows if not (r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]) or r["low"] <= 0)
    return {"bars": len(rows), "gaps": gaps, "missing_bars": int(missing), "invalid_bars": bad,
            "first": rows[0]["start"] if rows else None, "last": rows[-1]["start"] if rows else None}


# ---------------- cross-venue sanity (guarda de qualidade de dados) ----------------
def cross_venue_check(rx_price: float, others: dict, max_dev: float = 0.02, min_venues: int = 1):
    """rx_price: preço Revolut X; others: {venue: preço|None}. Desvio relativo à MEDIANA das outras venues.
    Devolve {status: OK|DEVIATION|INSUFFICIENT_DATA, dev, median, venues}. DEVIATION ⇒ veto (dados suspeitos)."""
    vals = sorted(float(v) for v in others.values() if v is not None and float(v) > 0)
    if rx_price is None or rx_price <= 0 or len(vals) < min_venues:
        return {"status": "INSUFFICIENT_DATA", "dev": None, "median": None, "venues": len(vals)}
    n = len(vals); med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    dev = rx_price / med - 1
    return {"status": "DEVIATION" if abs(dev) > max_dev else "OK", "dev": round(dev, 5), "median": med, "venues": n}


def live_sanity(coin: str, rx_price: float, venues=("coinbase", "kraken", "bitstamp"), max_dev=0.02, ccxt_mod=None, log=print):
    """Busca tickers públicos noutras venues. Sem ccxt/rede → INSUFFICIENT_DATA (sem efeito)."""
    base, quote = coin.split("-")
    px = {}
    for v in venues:
        try:
            ex = PublicOnly(v, ccxt_mod=ccxt_mod); t = ex.fetch_ticker(venue_symbol(base, quote, v))
            px[v] = t.get("last") or t.get("close")
        except Exception as e:
            px[v] = None
    return {**cross_venue_check(rx_price, px, max_dev), "prices": px}


def compare_series(a_rows, b_rows, max_dev=0.02):
    """Data-quality: fechos 1H em comum entre duas fontes. Devolve mediana/p99/máx do |desvio| e nº de horas > max_dev."""
    a = {r["start"]: r["close"] for r in a_rows}; b = {r["start"]: r["close"] for r in b_rows}
    common = sorted(set(a) & set(b)); d = sorted(abs(a[t] / b[t] - 1) for t in common if b[t] > 0)
    if not d: return {"common_bars": 0, "status": "INSUFFICIENT_DATA"}
    return {"common_bars": len(d), "median_dev": d[len(d) // 2], "p99_dev": d[int(len(d) * 0.99)], "max_dev": d[-1],
            "bars_over": sum(x > max_dev for x in d), "max_dev_threshold": max_dev}


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--venue", default="coinbase"); f.add_argument("--symbols", required=True)
    f.add_argument("--days", type=int, default=1095); f.add_argument("--until", type=int, default=None)
    f.add_argument("--out", default="data_ext/coinbase"); f.add_argument("--quote", default="USD")
    c = sub.add_parser("compare"); c.add_argument("--a", default="data"); c.add_argument("--b", default="data_ext/coinbase")
    c.add_argument("--out", default="desk/state/xvenue_history.json")
    s = sub.add_parser("sanity"); s.add_argument("--symbols", required=True); s.add_argument("--max-dev", type=float, default=0.02)
    a = ap.parse_args()
    if a.cmd == "fetch":
        ex = PublicOnly(a.venue); ex.load_markets()
        until = a.until or (int(time.time() * 1000) // H * H); since = until - a.days * 24 * H
        os.makedirs(a.out, exist_ok=True); rep = {}
        for b in a.symbols.split(","):
            sym = venue_symbol(b.strip().upper(), a.quote, a.venue)
            if sym not in ex.markets: print(f"{a.venue}: {sym} não listado"); continue
            rows = fetch_hourly(ex, sym, since, until)
            json.dump(rows, open(os.path.join(a.out, f"candles_{b.strip().upper()}-{a.quote}_60.json"), "w"))
            rep[sym] = quality(rows)
        json.dump({"venue": a.venue, "since": since, "until": until, "quality": rep}, open(os.path.join(a.out, "manifest.json"), "w"), indent=2)
        print(json.dumps(rep, indent=1))
    elif a.cmd == "compare":
        rep = {}
        for fn in sorted(os.listdir(a.a)):
            if fn.startswith("candles_") and os.path.exists(os.path.join(a.b, fn)):
                rep[fn[8:-8]] = compare_series(json.load(open(os.path.join(a.a, fn))), json.load(open(os.path.join(a.b, fn))))
        json.dump(rep, open(a.out, "w"), indent=1); print(json.dumps(rep, indent=1))
    else:
        from . import market
        for b in a.symbols.split(","):
            coin = f"{b.strip().upper()}-USD"
            rx = market.last_price(coin)
            print(coin, json.dumps(live_sanity(coin, rx, max_dev=a.max_dev)))


if __name__ == "__main__":
    main()
