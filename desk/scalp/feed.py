"""Dados PÚBLICOS da Revolut X para os bots Scalp: velas 1m e topo do order book. Só GET, sem chave, sem assinatura.
Limitador 1 req/s partilhado entre processos Scalp (flock num ficheiro), retry em 429/5xx/timeout.
"""
from __future__ import annotations
import fcntl, json, os, time
import requests

RX1 = "https://revx.revolut.com/api/1.0"
RX2 = "https://revx.revolut.com/api/2.0"
M1 = 60_000
WIN = 999                       # API: janela máx 1000 velas por pedido
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK = os.path.join(ROOT, "logs", "run", "revx_public_scalp.lock")
STATS = {"calls": 0, "errors": 0, "last_error": None}


def _throttle(min_gap=1.05):
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    fh = open(LOCK, "a+"); fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        fh.seek(0); txt = fh.read().strip()
        last = float(txt) if txt else 0.0
        wait = last + min_gap - time.time()
        if wait > 0: time.sleep(wait)
        fh.seek(0); fh.truncate(); fh.write(str(time.time())); fh.flush()
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def http_get(url, params=None, tries=3):
    for k in range(tries):
        _throttle(); STATS["calls"] += 1
        try:
            r = requests.get(url, params=params, timeout=20, headers={"Accept": "application/json"})
            if r.status_code == 200: return r.json()
            STATS["errors"] += 1; STATS["last_error"] = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429: return None
            time.sleep(float(r.headers.get("Retry-After", 1000)) / 1000 if r.status_code == 429 else 2 ** k)
        except (requests.RequestException, ValueError) as e:
            STATS["errors"] += 1; STATS["last_error"] = type(e).__name__; time.sleep(2 ** k)
    return None


def candles_1m(sym, since, until, get=http_get):
    """Velas 1m com start ∈ [since, until] (ms). Pede em janelas ≤999. Devolve (lista, ok)."""
    out, a, ok = {}, since, True
    while a <= until:
        b = min(until, a + (WIN - 1) * M1)
        j = get(f"{RX1}/public/candles/{sym}", {"interval": 1, "since": a, "until": b + M1 - 1})
        if j is None or "data" not in j: ok = False; break
        for r in j["data"]:
            try:
                s = int(r["start"]); x = {"o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                                          "c": float(r["close"]), "v": float(r["volume"])}
            except (KeyError, TypeError, ValueError):
                continue
            if a <= s <= b and x["c"] > 0 and x["l"] > 0 and x["h"] >= x["l"]: out[s] = x
        a = b + M1
    return [dict(ts=k, **out[k]) for k in sorted(out)], ok


def book(sym, get=http_get):
    j = get(f"{RX2}/public/order-book/{sym}", {"limit": 5})
    d = (j or {}).get("data", j) or {}
    try:
        bid, ask = float(d["bids"][0]["price"]), float(d["asks"][0]["price"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not (0 < bid < ask): return None
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "half_spread": (ask - bid) / 2 / mid, "ts": int(time.time() * 1000)}


def grid(rows, t0, t1, prev_close):
    """Grelha completa de minutos [t0, t1]; minuto ausente → O=H=L=C=fecho anterior, v=0, syn=True."""
    m = {r["ts"]: r for r in rows}; out, pc, syn = [], prev_close, 0
    for ts in range(t0, t1 + 1, M1):
        r = m.get(ts)
        if r is None:
            if pc is None: continue
            r = {"ts": ts, "o": pc, "h": pc, "l": pc, "c": pc, "v": 0.0, "syn": True}; syn += 1
        out.append(r); pc = r["c"]
    return out, syn


def history(sym, max_days=40, get=http_get, now_ms=None, log=print):
    """Todo o histórico 1m disponível (anda para trás em janelas de 999 até vir vazio)."""
    now_ms = now_ms or int(time.time() * 1000)
    end = (now_ms // M1) * M1 - M1; rows, empty = {}, 0
    b = end
    while b > now_ms - max_days * 86_400_000:
        a = b - (WIN - 1) * M1
        part, ok = candles_1m(sym, a, b, get)
        if not ok: log(f"{sym}: falha a {a}"); break
        if not part:
            empty += 1
            if empty >= 2: break
        for r in part: rows[r["ts"]] = r
        b = a - M1
    return [rows[k] for k in sorted(rows)]
