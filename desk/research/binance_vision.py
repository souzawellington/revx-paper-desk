"""Descarga de klines PÚBLICOS do arquivo data.binance.vision (sem API key, sem credenciais; só HTTP GET de ZIPs).
Inclui pares DESLISTADOS (o arquivo mantém-nos) para reduzir viés de sobrevivência.
python -m desk.research.binance_vision --interval 1d            (universo largo)
python -m desk.research.binance_vision --interval 1h --symbols BTC,ETH
Saída: data_ext/binance_vision/<interval>/<SYM>.json  [{start, open, high, low, close, volume, quote_volume}] (start em ms UTC)
Nota: desde 2025-01 os ficheiros spot trazem timestamps em MICROssegundos — normalizado para ms.
"""
from __future__ import annotations
import argparse, csv, io, json, os, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

BASE = "https://data.binance.vision/data/spot/monthly/klines"
OUT = "data_ext/binance_vision"
# Lista de candidatos = pares USDT que estiveram entre os maiores em algum momento 2018–2026, INCLUINDO mortos/deslistados
# (XMR, WAVES, XEM, OMG, LUNA, FTT, BCC, VEN, BCHABC, MATIC→POL...). Escolhida com conhecimento posterior → viés residual.
UNIVERSE = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "DOT", "LTC", "BCH", "BCC", "BCHABC", "LINK", "TRX", "EOS", "XLM",
            "XMR", "ETC", "NEO", "IOTA", "DASH", "ZEC", "WAVES", "ICX", "QTUM", "ONT", "OMG", "XEM", "VET", "VEN", "LUNA", "FTT",
            "MATIC", "POL", "AVAX", "UNI", "AAVE", "NEAR", "ATOM", "FIL", "SUI", "SHIB", "APT", "ARB", "OP", "TON", "PEPE",
            "ALGO", "XTZ", "BAT", "HBAR", "INJ"]


def months(y0=2017, m0=8, y1=2026, m1=9):
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield f"{y}-{m:02d}"; m += 1
        if m == 13: y, m = y + 1, 1


def parse_zip(blob: bytes) -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(blob)); rows = []
    for name in z.namelist():
        for r in csv.reader(io.TextIOWrapper(z.open(name), "utf-8")):
            if not r or not r[0].isdigit(): continue           # cabeçalho em alguns ficheiros
            t = int(r[0])
            if t > 10 ** 14: t //= 1000                          # µs → ms (ficheiros 2025+)
            rows.append({"start": t, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]),
                         "volume": float(r[5]), "quote_volume": float(r[7])})
    return rows


def get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(1 + k)
        except Exception:
            time.sleep(1 + k)
    return None


def fetch_symbol(base, interval, end="2026-09"):
    pair = f"{base}USDT"; y1, m1 = map(int, end.split("-"))
    urls = [f"{BASE}/{pair}/{interval}/{pair}-{interval}-{ym}.zip" for ym in months(y1=y1, m1=m1)]
    with ThreadPoolExecutor(8) as ex: blobs = list(ex.map(get, urls))
    rows = {}
    for b in blobs:
        if b: rows.update({r["start"]: r for r in parse_zip(b)})
    return [rows[k] for k in sorted(rows)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--interval", default="1d"); ap.add_argument("--symbols", default="")
    ap.add_argument("--end", default="2026-09"); a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or UNIVERSE
    od = os.path.join(OUT, a.interval); os.makedirs(od, exist_ok=True); man = {}
    for s in syms:
        rows = fetch_symbol(s, a.interval, a.end)
        if rows: json.dump(rows, open(os.path.join(od, f"{s}.json"), "w"))
        man[s] = {"bars": len(rows), "first": rows[0]["start"] if rows else None, "last": rows[-1]["start"] if rows else None}
        print(s, man[s], flush=True)
    json.dump({"source": "data.binance.vision (público)", "quote": "USDT", "end_month": a.end, "symbols": man},
              open(os.path.join(od, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
