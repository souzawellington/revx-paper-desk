"""Dados públicos Revolut X para o desk: universo e velas com cache incremental (respeita 1 req/s público)."""
from __future__ import annotations
import json, os, time
from bot.revolutx import RevolutXClient
from bot.revolutx.rules import pairs_to_rules
from bot.dashboard import ReadOnlyClient
from . import store

_PUB = None
IV_MS = {60: 3_600_000, 240: 14_400_000, 1440: 86_400_000}


def pub():
    global _PUB
    if _PUB is None: _PUB = ReadOnlyClient(RevolutXClient())   # só GETs; o cliente aplica 1 req/s nos públicos
    return _PUB


def universe(rules, client=None) -> list[str]:
    pairs = (client or pub()).public_pairs()
    return sorted(s for s, r in pairs_to_rules(pairs).items()
                  if s.endswith("-" + rules.quote) and r.active and s.split("-")[0] not in rules.exclude)


def candles(symbol: str, interval: int, bars: int, now: int | None = None, client=None, since: int | None = None) -> list[dict]:
    """Velas FECHADAS. Cache em state/cache; só pede o que falta (janelas de 100 velas)."""
    c = client or pub(); iv = IV_MS[interval]; now = now or store.now_ms()
    d = os.path.join(store.STATE, "cache"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{symbol}_{interval}.json")
    rows = {r["start"]: r for r in (json.load(open(p)) if os.path.exists(p) else [])}
    want_from = since if since is not None else now - bars * iv
    have = sorted(rows)
    segments = []
    if not have or have[0] > want_from: segments.append((want_from, have[0] if have else now))
    if have: segments.append((have[-1] + iv, now))   # (re)busca a partir da última vela em cache
    for a, b in segments:
        until = b
        while until > a:
            frm = max(a, until - 100 * iv)
            for r in c.public_candles(symbol, interval, frm, until, None) or []:
                rows[int(r["start"])] = {"start": int(r["start"]), **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}}
            until = frm
    out = [rows[k] for k in sorted(rows) if k + iv <= now]
    json.dump(out, open(p, "w"))
    return [r for r in out if r["start"] >= want_from]


def last_price(symbol, client=None):
    t = (client or pub()).public_tickers([symbol])
    return float(t[0]["mid"]) if t else None
