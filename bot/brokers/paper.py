from .base import Broker, Order, Position


class PaperBroker(Broker):
    """Simulação local 24/7, quantidades fracionárias, taxa taker + slippage."""
    def __init__(self, cash: float = 100_000.0, slippage: float = 0.001, taker_fee: float = 0.0009, rules=None):
        self._cash, self.slip, self.fee, self._pos, self.fills = cash, slippage, taker_fee, {}, []
        self.rules = rules or {}

    def cash(self): return self._cash
    def positions(self): return self._pos

    def equity(self, prices):
        return self._cash + sum(p.qty * prices.get(t, p.entry) for t, p in self._pos.items())

    def submit(self, o: Order, price: float):
        if o.order_type == "LIMIT" and o.limit_price is not None:
            if (o.side == "BUY" and price > o.limit_price) or (o.side == "SELL" and price < o.limit_price):
                return {"status": "NOT_FILLED"}
        px = price * (1 + self.slip if o.side == "BUY" else 1 - self.slip)
        if o.side == "BUY":
            cost = px * o.qty * (1 + self.fee)
            if cost > self._cash:
                return {"status": "REJECTED", "why": "cash"}
            self._cash -= cost
            p = self._pos.get(o.ticker)
            if p:
                p.entry = (p.entry * p.qty + px * o.qty) / (p.qty + o.qty); p.qty += o.qty
            else:
                self._pos[o.ticker] = Position(o.ticker, o.qty, px, px)
        else:
            p = self._pos.get(o.ticker)
            if not p: return {"status": "REJECTED", "why": "no position"}
            q = min(o.qty, p.qty); self._cash += px * q * (1 - self.fee); p.qty -= q
            if p.qty <= 1e-12: del self._pos[o.ticker]
        fill = {"status": "FILLED", "ticker": o.ticker, "side": o.side, "qty": o.qty, "price": px}
        self.fills.append(fill); return fill
