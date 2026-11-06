"""Cliente REST Revolut X (cripto).

Fontes oficiais:
- https://developer.revolut.com/docs/api/revolut-x-crypto-exchange   (referência; auth; rate limits)
- https://github.com/revolut-engineering/revolut-x-api/blob/master/revolut-x-api-for-llm.md (spec resumida oficial)
- https://developer.revolut.codes/docs/api/revolut-x-crypto-exchange/operations/place-order.md

Autenticação (docs, secção "Authentication headers" / "Signing a request"):
  X-Revx-API-Key   : chave de 64 caracteres criada na web app Revolut X
  X-Revx-Timestamp : Unix epoch em MILISSEGUNDOS
  X-Revx-Signature : base64( Ed25519_sign( timestamp + METHOD + path(/api/...) + query(sem '?') + body_json_minificado ) )
Base URL: https://revx.revolut.com/api/1.0
"""
from __future__ import annotations
import base64, json, threading, time, uuid
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlencode

BASE_HOST = "https://revx.revolut.com"
API_PREFIX = "/api/1.0"


def load_private_key(pem: bytes):
    """Chave gerada por `openssl genpkey -algorithm ed25519 -out private.pem` (docs: 'Generate an Ed25519 key pair')."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("a chave privada tem de ser Ed25519")
    return key


def minify(body: Optional[dict]) -> str:
    return "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def build_message(ts_ms: int | str, method: str, path: str, query: str = "", body: str = "") -> bytes:
    """Concatenação sem separadores, na ordem exata dos docs."""
    if not path.startswith("/api"):
        raise ValueError("path tem de começar em /api")
    return f"{ts_ms}{method.upper()}{path}{query}{body}".encode("utf-8")


def sign_message(private_key, message: bytes) -> str:
    return base64.b64encode(private_key.sign(message)).decode()


class RateLimiter:
    """Token bucket simples. Docs: autenticados 1000 req/min (100/s); place order 10/s e 1000/dia;
    públicos (tickers/candles/pairs) 1 req/s; public order-book/last-trades 20 req/10s."""
    def __init__(self, rate_per_s: float, burst: int):
        self.rate, self.cap, self.tokens, self.t, self.lock = rate_per_s, burst, float(burst), time.monotonic(), threading.Lock()

    def acquire(self, sleep=time.sleep):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.cap, self.tokens + (now - self.t) * self.rate); self.t = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                sleep(wait); self.tokens = 0; self.t = time.monotonic()
            else:
                self.tokens -= 1


class RevolutXError(Exception):
    def __init__(self, status, payload):
        super().__init__(f"HTTP {status}: {payload}"); self.status, self.payload = status, payload


class RevolutXClient:
    def __init__(self, api_key: Optional[str] = None, private_key=None, session=None,
                 clock=lambda: time.time(), sleep=time.sleep, max_retries: int = 3):
        import requests
        self.api_key, self.pk = api_key, private_key
        self.s = session or requests.Session()
        self.clock, self.sleep, self.max_retries = clock, sleep, max_retries
        self.rl_auth = RateLimiter(1000 / 60, 100)     # 1000 tokens/min, 100/s
        self.rl_order = RateLimiter(10, 10)            # place order: 10/s
        self.rl_public = RateLimiter(1, 1)             # public tickers/candles/pairs: 1/s
        self.orders_today, self.order_day = 0, None    # place order: 1000/dia (não se aplica a sub-contas)

    # ---------- núcleo ----------
    def _request(self, method: str, endpoint: str, params: dict | None = None, body: dict | None = None,
                 auth: bool = True, limiter: RateLimiter | None = None) -> Any:
        path = API_PREFIX + endpoint
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, safe=",")
        body_s = minify(body)
        url = BASE_HOST + path + (f"?{query}" if query else "")
        for attempt in range(self.max_retries + 1):
            (limiter or (self.rl_auth if auth else self.rl_public)).acquire(self.sleep)
            headers = {"Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            if auth:
                if not (self.api_key and self.pk):
                    raise RevolutXError(0, "credenciais Revolut X ausentes")
                ts = int(self.clock() * 1000)
                headers.update({"X-Revx-API-Key": self.api_key, "X-Revx-Timestamp": str(ts),
                                "X-Revx-Signature": sign_message(self.pk, build_message(ts, method, path, query, body_s))})
            r = self.s.request(method, url, headers=headers, data=body_s.encode() if body is not None else None, timeout=15)
            if r.status_code == 429 and attempt < self.max_retries:
                # Docs: header Retry-After em MILISSEGUNDOS
                self.sleep(float(r.headers.get("Retry-After", 1000)) / 1000); continue
            if r.status_code >= 500 and attempt < self.max_retries:
                self.sleep(2 ** attempt); continue
            if r.status_code >= 400:
                try: payload = r.json()
                except Exception: payload = r.text
                raise RevolutXError(r.status_code, payload)
            if r.status_code == 204 or not r.content:
                return None
            return r.json()
        raise RevolutXError(429, "retries esgotados")

    # ---------- público (sem auth) ----------
    def public_pairs(self, region=None) -> dict:
        """GET /api/1.0/public/configuration/pairs -> {"BTC/USD": {base_step, quote_step, min_order_size, max_order_size, min_order_size_quote, status}}"""
        return self._request("GET", "/public/configuration/pairs", {"region": region}, auth=False)

    def public_tickers(self, symbols=None, region=None) -> list:
        """GET /api/1.0/public/tickers?symbols=BTC-USD,ETH-USD -> data[{symbol:'BTC/USD', bid, ask, mid, last_price,...}]"""
        p = {"symbols": ",".join(symbols) if symbols else None, "region": region}
        return self._request("GET", "/public/tickers", p, auth=False)["data"]

    def public_candles(self, symbol, interval=60, since=None, until=None, region=None) -> list:
        """GET /api/1.0/public/candles/{symbol} -> data[{start(ms), open, high, low, close, volume}] (strings)"""
        p = {"interval": interval, "since": since, "until": until, "region": region}
        return self._request("GET", f"/public/candles/{symbol}", p, auth=False)["data"]

    # ---------- autenticado ----------
    def balances(self) -> list:
        """GET /api/1.0/balances -> [{currency, available, reserved, staked?, total}]"""
        return self._request("GET", "/balances")

    def active_orders(self, symbols=None, limit=100) -> list:
        """GET /api/1.0/orders/active (paginado por metadata.next_cursor)"""
        out, cursor = [], None
        while True:
            r = self._request("GET", "/orders/active", {"symbols": ",".join(symbols) if symbols else None,
                                                         "cursor": cursor, "limit": limit})
            out += r.get("data", []); cursor = (r.get("metadata") or {}).get("next_cursor")
            if not cursor: return out

    def get_order(self, venue_order_id) -> dict:
        return self._request("GET", f"/orders/{venue_order_id}")

    def place_order(self, symbol: str, side: str, *, base_size: Decimal | str | None = None,
                    quote_size: Decimal | str | None = None, limit_price: Decimal | str | None = None,
                    post_only: bool = False, client_order_id: str | None = None) -> dict:
        """POST /api/1.0/orders. order_configuration contém exatamente um de 'limit'|'market';
        cada um exatamente um de base_size|quote_size. side: 'buy'|'sell'. Valores decimais como STRING."""
        if (base_size is None) == (quote_size is None):
            raise ValueError("exatamente um de base_size/quote_size")
        sz = {"base_size": str(base_size)} if base_size is not None else {"quote_size": str(quote_size)}
        if limit_price is not None:
            cfg = {"limit": {**sz, "price": str(limit_price)}}
            if post_only: cfg["limit"]["execution_instructions"] = ["post_only"]
        else:
            cfg = {"market": sz}
        day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        if day != self.order_day: self.order_day, self.orders_today = day, 0
        if self.orders_today >= 1000:
            raise RevolutXError(429, "limite diário de 1000 ordens (docs) atingido")
        body = {"client_order_id": client_order_id or str(uuid.uuid4()), "symbol": symbol,
                "side": side.lower(), "order_configuration": cfg}
        res = self._request("POST", "/orders", body=body, limiter=self.rl_order)
        self.orders_today += 1
        return res

    def _count_order(self):
        day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        if day != self.order_day: self.order_day, self.orders_today = day, 0
        if self.orders_today >= 1000:
            raise RevolutXError(429, "limite diário de 1000 ordens (docs) atingido")

    def place_tpsl(self, symbol: str, side: str, *, base_size, take_profit=None, stop_loss=None,
                   tp_limit=None, sl_limit=None, client_order_id: str | None = None) -> dict:
        """POST /api/1.0/orders com order_configuration.tpsl (docs revolut-x-api-for-llm.md): ordem do lado do BROKER
        que fica em repouso; sell → TP dispara com preço ≥ trigger, SL com preço ≤ trigger. Sem limit_price → mercado."""
        if take_profit is None and stop_loss is None: raise ValueError("tpsl precisa de take_profit e/ou stop_loss")
        cfg = {"base_size": str(base_size)}
        if take_profit is not None:
            cfg["take_profit"] = {"trigger_price": str(take_profit), **({"limit_price": str(tp_limit)} if tp_limit is not None else {})}
        if stop_loss is not None:
            cfg["stop_loss"] = {"trigger_price": str(stop_loss), **({"limit_price": str(sl_limit)} if sl_limit is not None else {})}
        self._count_order()
        body = {"client_order_id": client_order_id or str(uuid.uuid4()), "symbol": symbol, "side": side.lower(),
                "order_configuration": {"tpsl": cfg}}
        res = self._request("POST", "/orders", body=body, limiter=self.rl_order); self.orders_today += 1
        return res

    def place_conditional(self, symbol: str, side: str, *, base_size, trigger_price, limit_price=None,
                          client_order_id: str | None = None) -> dict:
        """POST /api/1.0/orders com order_configuration.conditional (stop simples: dispara mercado/limite no trigger)."""
        cfg = {"base_size": str(base_size), "trigger_price": str(trigger_price)}
        if limit_price is not None: cfg["limit_price"] = str(limit_price)
        self._count_order()
        body = {"client_order_id": client_order_id or str(uuid.uuid4()), "symbol": symbol, "side": side.lower(),
                "order_configuration": {"conditional": cfg}}
        res = self._request("POST", "/orders", body=body, limiter=self.rl_order); self.orders_today += 1
        return res

    def historical_orders(self, symbols=None, start_date=None, end_date=None, limit=100) -> list:
        """GET /api/1.0/orders/historical (máx. 1 semana por pedido)."""
        out, cursor = [], None
        while True:
            r = self._request("GET", "/orders/historical", {"symbols": ",".join(symbols) if symbols else None,
                              "start_date": start_date, "end_date": end_date, "cursor": cursor, "limit": limit})
            out += r.get("data", []); cursor = (r.get("metadata") or {}).get("next_cursor")
            if not cursor: return out

    def order_fills(self, venue_order_id) -> list:
        """GET /api/1.0/orders/fills/{venue_order_id}"""
        return (self._request("GET", f"/orders/fills/{venue_order_id}") or {}).get("data", [])

    def cancel_order(self, venue_order_id) -> None:
        """DELETE /api/1.0/orders/{venue_order_id} -> 204"""
        return self._request("DELETE", f"/orders/{venue_order_id}")

    def cancel_all(self) -> None:
        """DELETE /api/1.0/orders -> cancela todas as ordens ativas"""
        return self._request("DELETE", "/orders")
