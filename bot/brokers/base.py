from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Order:
    ticker: str          # símbolo BASE-QUOTE (ex. BTC-USD)
    side: str            # BUY | SELL
    qty: float           # quantidade em moeda base (fracionária)
    order_type: str      # MARKET | LIMIT
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    reason: str = ""


@dataclass
class Position:
    ticker: str
    qty: float
    entry: float
    local_peak: float
    atr_stop: Optional[float] = None


class Broker(ABC):
    rules: dict = {}

    @abstractmethod
    def equity(self, prices: dict) -> float: ...
    @abstractmethod
    def cash(self) -> float: ...
    @abstractmethod
    def positions(self) -> dict[str, Position]: ...
    @abstractmethod
    def submit(self, order: Order, price: float) -> dict: ...

    def quantize(self, symbol: str, qty: float, price: float) -> float:
        from ..revolutx.rules import DEFAULT_RULES
        r = (self.rules or {}).get(symbol, DEFAULT_RULES)
        return float(r.quantize_base(qty, price))
