"""Broker real Revolut X. Só ativo com BOT_BROKER=revolutx E BOT_DRY_RUN=0.
Saldos: GET /balances; ordens: POST /orders (market, base_size); cancel: DELETE /orders[/{id}].
O endpoint /balances não devolve preço de entrada: é persistido localmente em state_file (ver GAPS.md)."""
from __future__ import annotations
import json, os
from .base import Broker, Order, Position
from ..revolutx.client import RevolutXClient, load_private_key
from ..revolutx.rules import pairs_to_rules


class RevolutXBroker(Broker):
    def __init__(self, client: RevolutXClient, quote: str, rules: dict, state_file: str):
        self.c, self.quote, self.rules, self.state_file = client, quote, rules, state_file
        self.state = json.load(open(state_file)) if os.path.exists(state_file) else {}

    @classmethod
    def from_env(cls, cfg):
        key = os.environ["REVX_API_KEY"]                       # PLACEHOLDER: chave de 64 chars
        pem = open(os.environ["REVX_PRIVATE_KEY_PATH"], "rb").read()  # PLACEHOLDER: private.pem
        c = RevolutXClient(key, load_private_key(pem))
        return cls(c, cfg.quote_currency, pairs_to_rules(c.public_pairs(cfg.region)),
                   os.path.join(cfg.log_dir, "revx_positions.json"))

    def _save(self):
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        json.dump(self.state, open(self.state_file, "w"))

    def _bal(self):
        return {b["currency"]: b for b in self.c.balances()}

    def cash(self):
        b = self._bal().get(self.quote)
        return float(b["available"]) if b else 0.0

    def positions(self):
        out = {}
        for cur, b in self._bal().items():
            if cur == self.quote: continue
            sym = f"{cur}-{self.quote}"
            qty = float(b["total"]) - float(b.get("staked") or 0)
            if qty <= 0 or sym not in self.rules: continue
            st = self.state.get(sym, {})
            entry = st.get("entry"); peak = st.get("peak", entry)
            if entry is None:   # posição pré-existente sem registo: entrada desconhecida
                continue        # o bot NÃO gere posições que não abriu (GAPS.md)
            out[sym] = Position(sym, qty, entry, peak, st.get("atr_stop"))
        return out

    def equity(self, prices):
        bal = self._bal(); eq = 0.0
        for cur, b in bal.items():
            if cur == self.quote: eq += float(b["total"])
            else: eq += float(b["total"]) * prices.get(f"{cur}-{self.quote}", 0.0)
        return eq

    def update_peak(self, sym, price):
        if sym in self.state:
            self.state[sym]["peak"] = max(self.state[sym].get("peak", price), price); self._save()

    def submit(self, o: Order, price: float):
        r = self.rules[o.ticker]
        qty = r.quantize_base(o.qty, price)
        if qty == 0:
            return {"status": "REJECTED", "why": "abaixo de min_order_size/min_order_size_quote"}
        lp = r.quantize_price(o.limit_price) if o.order_type == "LIMIT" and o.limit_price else None
        res = self.c.place_order(o.ticker, o.side.lower(), base_size=qty, limit_price=lp)
        if o.side == "BUY":
            st = self.state.get(o.ticker)
            if st:
                tot = st["qty"] + float(qty); st["entry"] = (st["entry"] * st["qty"] + price * float(qty)) / tot; st["qty"] = tot
            else:
                self.state[o.ticker] = {"entry": price, "peak": price, "qty": float(qty)}
            if o.stop_price: self.state[o.ticker]["atr_stop"] = o.stop_price
        else:
            self.state.pop(o.ticker, None)
        self._save()
        d = res.get("data") if isinstance(res, dict) else res
        d = d[0] if isinstance(d, list) else d
        return {"status": "SUBMITTED", **(d or {})}
