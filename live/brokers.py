"""Brokers do executor autónomo — MESMA interface para LIVE (Revolut X assinado) e PAPER (simulado localmente).

LiveBroker: envolve o RevolutXClient e instala uma WHITELIST de caminhos HTTP. Só passa:
  GET  /balances, /orders/active, /orders/historical, /orders/{id}, /orders/fills/{id}, /public/*
  POST /orders                      (limit / market / tpsl — nada mais)
  DELETE /orders/{id}               (cancelar UMA ordem nossa; nunca DELETE /orders = cancel-all)
Qualquer outro caminho/método levanta PermissionError. A API Revolut X não tem endpoints de depósito/levantamento/
transferência; mesmo que viesse a ter, a whitelist bloqueia-os. Este módulo não contém nenhuma chamada desse tipo.

PaperBroker: simula a exchange com velas 1H PÚBLICAS reais (pessimista): limit buy enche só se a mínima ficar
ESTRITAMENTE abaixo do preço; tpsl: stop (mercado, taker + slippage) tem prioridade se stop e TP na mesma vela;
TP limite enche se a máxima ficar estritamente acima (maker 0%). Estado persistido em JSON.
"""
from __future__ import annotations
import json, math, os, re, uuid
from decimal import Decimal, ROUND_DOWN, ROUND_UP

H = 3_600_000
FORBIDDEN_WORDS = ("withdraw", "transfer", "deposit", "payout")

_ALLOWED = [("GET", re.compile(r"^/api/1\.0/(balances|orders/active|orders/historical|orders/[0-9a-fA-F-]{8,}|orders/fills/[0-9a-fA-F-]{8,}|public/.*)$")),
            ("POST", re.compile(r"^/api/1\.0/orders$")),
            ("DELETE", re.compile(r"^/api/1\.0/orders/[0-9a-fA-F-]{8,}$"))]


def path_allowed(method: str, path: str) -> bool:
    if any(w in path.lower() for w in FORBIDDEN_WORDS): return False
    return any(m == method.upper() and rx.match(path) for m, rx in _ALLOWED)


def dash(sym: str) -> str: return sym.replace("/", "-")


def q_floor(x, step) -> str:
    st = Decimal(str(step)); return str((Decimal(str(x)) / st).to_integral_value(ROUND_DOWN) * st)


def q_ceil(x, step) -> str:
    st = Decimal(str(step)); return str((Decimal(str(x)) / st).to_integral_value(ROUND_UP) * st)


def norm_order(o: dict) -> dict:
    """Ordem Revolut X -> dicionário normalizado."""
    tb = o.get("triggered_by") or {}
    return {"id": o.get("id") or o.get("venue_order_id"), "coid": o.get("client_order_id"), "symbol": dash(o.get("symbol", "")),
            "side": o.get("side"), "type": o.get("type"), "status": o.get("status") or o.get("state"),
            "qty": float(o.get("quantity") or 0), "filled": float(o.get("filled_quantity") or 0),
            "avg": float(o["average_fill_price"]) if o.get("average_fill_price") not in (None, "") else None,
            "price": float(o["price"]) if o.get("price") not in (None, "") else None,
            "linked_id": (o.get("on_fill") or {}).get("id"), "trigger_reason": tb.get("reason")}


class LiveBroker:
    kind = "live"

    def __init__(self, client):
        self.c = client
        orig = client._request

        def guarded(method, endpoint, *a, **k):
            path = "/api/1.0" + endpoint
            if not path_allowed(method, path):
                raise PermissionError(f"executor: {method} {path} fora da whitelist")
            return orig(method, endpoint, *a, **k)
        client._request = guarded
        self._pairs = None

    # ---- leitura ----
    def balances(self) -> dict:
        return {b["currency"]: {"available": float(b["available"]), "total": float(b["total"])} for b in self.c.balances()}

    def ticker(self, symbol) -> dict:
        t = self.c.public_tickers([symbol])[0]
        return {k: float(t[k]) for k in ("bid", "ask", "mid", "last_price") if t.get(k) not in (None, "")}

    def pairs(self) -> dict:
        if self._pairs is None: self._pairs = {dash(k): v for k, v in self.c.public_pairs().items()}
        return self._pairs

    def candles(self, symbol, interval, since):
        return [{"start": int(c["start"]), **{k: float(c[k]) for k in ("open", "high", "low", "close", "volume")}}
                for c in self.c.public_candles(symbol, interval, since=since)]

    def active_orders(self) -> list:
        return [norm_order(o) for o in self.c.active_orders()]

    def get_order(self, oid) -> dict:
        r = self.c.get_order(oid); return norm_order(r.get("data", r) if isinstance(r, dict) else r)

    def find_by_coid(self, coid, now_ms=None):
        """Ordem nossa com resultado desconhecido (timeout no POST): procurar nas activas e no histórico (≤ 1 semana)."""
        for o in self.active_orders():
            if o.get("coid") == coid: return o
        import time as _t
        end = now_ms or int(_t.time() * 1000)
        for o in self.c.historical_orders(start_date=end - 7 * 86_400_000, end_date=end):
            if o.get("client_order_id") == coid: return norm_order(o)
        return None

    # ---- escrita (só via whitelist) ----
    def limit_buy(self, symbol, base_size, price, coid, post_only=True):
        r = self.c.place_order(symbol, "buy", base_size=base_size, limit_price=price, post_only=post_only, client_order_id=coid)
        return norm_order(r.get("data", r))

    def tpsl_sell(self, symbol, base_size, tp, sl, coid):
        """Ordem do lado do broker: TP como LIMITE no próprio preço (tende a maker), SL a mercado (garante saída)."""
        r = self.c.place_tpsl(symbol, "sell", base_size=base_size, take_profit=tp, tp_limit=tp, stop_loss=sl, client_order_id=coid)
        return norm_order(r.get("data", r))

    def market_sell(self, symbol, base_size, coid):
        r = self.c.place_order(symbol, "sell", base_size=base_size, client_order_id=coid)
        return norm_order(r.get("data", r))

    def cancel(self, oid):
        return self.c.cancel_order(oid)


class PaperBroker:
    """Exchange simulada (paper_autonomous). `market` dá ticker/candles públicos; nada é enviado a lado nenhum."""
    kind = "paper"

    def __init__(self, path, market, cash=65.0, quote="USD", taker=0.0009, slippage=0.001, maker=0.0, clock=None):
        self.path, self.m, self.taker, self.slip, self.maker, self.quote = path, market, taker, slippage, maker, quote
        self.clock = clock
        if os.path.exists(path):
            self.s = json.load(open(path))
        else:
            self.s = {"bal": {quote: cash}, "orders": {}, "last_ts": None}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True); tmp = self.path + ".tmp"
        json.dump(self.s, open(tmp, "w"), indent=1); os.replace(tmp, self.path)

    # ---- leitura ----
    def _reserved(self, cur):
        r = 0.0
        for o in self.s["orders"].values():
            if o["status"] not in ("new", "partially_filled"): continue
            base, q = o["symbol"].split("-")
            if o["side"] == "buy" and cur == q: r += (o["qty"] - o["filled"]) * o["price"]
            if o["side"] == "sell" and cur == base: r += o["qty"] - o["filled"]
        return r

    def balances(self):
        return {c: {"available": v - self._reserved(c), "total": v} for c, v in self.s["bal"].items() if v > 1e-12}

    def ticker(self, symbol): return self.m.ticker(symbol)
    def pairs(self): return self.m.pairs()
    def candles(self, symbol, interval, since): return self.m.candles(symbol, interval, since)

    def active_orders(self):
        return [self._view(o) for o in self.s["orders"].values() if o["status"] in ("new", "partially_filled")]

    def get_order(self, oid): return self._view(self.s["orders"][oid])

    def _view(self, o): return {k: o.get(k) for k in ("id", "coid", "symbol", "side", "type", "status", "qty", "filled", "avg", "price", "trigger_reason")}

    # ---- escrita (simulada) ----
    def _new(self, **o):
        for x in self.s["orders"].values():
            if x["coid"] == o["coid"]: return self._view(x)          # idempotente por client_order_id
        oid = str(uuid.uuid4()); o.update(id=oid, filled=0.0, avg=None, status="new", trigger_reason=None)
        self.s["orders"][oid] = o; self.save(); return self._view(o)

    def limit_buy(self, symbol, base_size, price, coid, post_only=True):
        q = float(base_size); px = float(price)
        if q * px > self.balances().get(self.quote, {}).get("available", 0) + 1e-9:
            return {"id": None, "coid": coid, "status": "rejected", "symbol": symbol}
        o = self._new(coid=coid, symbol=symbol, side="buy", type="limit", qty=q, price=px, placed_ts=self._now())
        if not post_only and o["status"] == "new" and o["filled"] == 0:
            # limite "marketable" (só o ensaio paper_fast usa): se o ask actual ≤ limite, enche JÁ ao ask + slippage, taker
            try: ask = float(self.m.ticker(symbol)["ask"])
            except Exception: ask = None
            if ask and ask <= px:
                self._fill(self.s["orders"][o["id"]], q, min(px, ask * (1 + self.slip)), self.taker); self.save()
                return self._view(self.s["orders"][o["id"]])
        return o

    def tpsl_sell(self, symbol, base_size, tp, sl, coid):
        base = symbol.split("-")[0]
        if float(base_size) > self.balances().get(base, {}).get("available", 0) + 1e-12:
            return {"id": None, "coid": coid, "status": "rejected", "symbol": symbol}
        return self._new(coid=coid, symbol=symbol, side="sell", type="tpsl", qty=float(base_size), price=None,
                         tp=float(tp), sl=float(sl), placed_ts=self._now())

    def market_sell(self, symbol, base_size, coid):
        base = symbol.split("-")[0]; q = min(float(base_size), self.balances().get(base, {}).get("available", 0))
        if q <= 0: return {"id": None, "coid": coid, "status": "rejected", "symbol": symbol}
        o = self._new(coid=coid, symbol=symbol, side="sell", type="market", qty=q, price=None, placed_ts=self._now())
        px = self.m.ticker(symbol)["bid"] * (1 - self.slip)
        self._fill(self.s["orders"][o["id"]], q, px, self.taker); self.save(); return self._view(self.s["orders"][o["id"]])

    def cancel(self, oid):
        o = self.s["orders"].get(oid)
        if o and o["status"] in ("new", "partially_filled"): o["status"] = "cancelled"; self.save()

    def _now(self):
        return self.clock() if self.clock else None

    def _fill(self, o, q, px, fee):
        base, quote = o["symbol"].split("-"); b = self.s["bal"]
        if o["side"] == "buy":
            b[quote] = b.get(quote, 0) - q * px * (1 + fee); b[base] = b.get(base, 0) + q
        else:
            b[base] = b.get(base, 0) - q; b[quote] = b.get(quote, 0) + q * px * (1 - fee)
        o["avg"] = ((o["avg"] or 0) * o["filled"] + px * q) / (o["filled"] + q); o["filled"] += q
        o["status"] = "filled" if o["filled"] >= o["qty"] - 1e-12 else "partially_filled"

    M1 = 60_000

    def _tpsl_bar(self, o, c):
        """Uma vela (1H ou 1m) contra uma ordem tpsl: stop tem prioridade (gap → abertura); TP limite estritamente acima."""
        rem = o["qty"] - o["filled"]
        if c["open"] <= o["sl"]:
            o["trigger_reason"] = "stop_loss"; self._fill(o, rem, c["open"] * (1 - self.slip), self.taker)
        elif c["low"] <= o["sl"]:
            o["trigger_reason"] = "stop_loss"; self._fill(o, rem, o["sl"] * (1 - self.slip), self.taker)
        elif c["open"] >= o["tp"]:
            o["trigger_reason"] = "take_profit"; self._fill(o, rem, c["open"], self.maker)
        elif c["high"] > o["tp"]:
            o["trigger_reason"] = "take_profit"; self._fill(o, rem, o["tp"], self.maker)

    def _tpsl_minutes(self, o, start, end):
        """Velas 1m FECHADAS em [start, end) — cobre a parte de uma hora que nenhuma vela 1H fechada cobre
        (hora da colocação, hora corrente)."""
        try:
            m1 = [c for c in self.m.candles(o["symbol"], 1, start, until=end) if start <= c["start"] and c["start"] + self.M1 <= end]
        except Exception:
            return
        for c in sorted(m1, key=lambda c: c["start"]):
            self._tpsl_bar(o, c); o["checked_to"] = c["start"] + self.M1
            if o["status"] == "filled": break

    def _advance_tpsl(self, o, now_ms):
        """Stop/TP do broker simulado: horas completas com velas 1H; as pontas parciais (desde a colocação até ao fim
        dessa hora, e a hora corrente até agora) com velas 1m. Antes, a hora da colocação era ignorada — o stop ficava
        cego até ~59 min após cada colocação/recolocação (ex.: BE)."""
        since = o.get("checked_to") or o.get("placed_ts") or now_ms - H
        if since % H:                                   # ponta inicial: hora começada antes de `since`
            hour_end = since // H * H + H
            self._tpsl_minutes(o, since, min(now_ms, hour_end))
            if o["status"] == "filled": return
            if hour_end > now_ms: return                # ainda estamos nessa hora
            o["checked_to"] = since = hour_end          # hora fechada: minutos disponíveis já avaliados (sem 1m = comportamento antigo)
        bars = [c for c in self.m.candles(o["symbol"], 60, since) if c["start"] >= since and c["start"] + H <= now_ms]
        for c in bars:
            self._tpsl_bar(o, c); o["checked_to"] = c["start"] + H
            if o["status"] == "filled": return
        since = o.get("checked_to") or since
        if since < now_ms:                              # ponta final: hora corrente, só minutos fechados
            self._tpsl_minutes(o, since, now_ms)

    def advance(self, now_ms):
        """Faz corresponder as ordens activas às velas FECHADAS desde a colocação de cada ordem
        (limit: 1H, ignorando a hora da colocação — pessimista; tpsl: ver _advance_tpsl)."""
        for o in list(self.s["orders"].values()):
            if o["status"] not in ("new", "partially_filled") or o["type"] == "market": continue
            if o["type"] == "tpsl":
                self._advance_tpsl(o, now_ms); continue
            since = (o.get("checked_to") or o.get("placed_ts") or now_ms - H)
            bars = [c for c in self.m.candles(o["symbol"], 60, since) if c["start"] >= since // H * H and c["start"] + H <= now_ms]
            # a vela em que a ordem foi colocada só conta se começou depois da colocação (pessimista: ignorar)
            bars = [c for c in bars if c["start"] >= (o.get("placed_ts") or 0)]
            for c in bars:
                rem = o["qty"] - o["filled"]
                if o["type"] == "limit" and c["low"] < o["price"]:
                    self._fill(o, rem, o["price"], self.maker)
                o["checked_to"] = c["start"] + H
                if o["status"] == "filled": break
        self.save()
