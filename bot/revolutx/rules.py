"""Incrementos/mínimos por par (GET /public/configuration/pairs). Aritmética Decimal."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


@dataclass(frozen=True)
class PairRules:
    base_step: Decimal
    quote_step: Decimal
    min_order_size: Decimal
    max_order_size: Decimal
    min_order_size_quote: Decimal
    active: bool = True

    @classmethod
    def from_api(cls, d: dict) -> "PairRules":
        D = lambda k, dflt="0": Decimal(str(d.get(k, dflt)))
        return cls(D("base_step"), D("quote_step"), D("min_order_size"), D("max_order_size", "1e18"),
                   D("min_order_size_quote"), d.get("status", "active") == "active")

    def quantize_base(self, qty: float | Decimal, price: float | Decimal) -> Decimal:
        """Arredonda PARA BAIXO ao base_step; devolve 0 se abaixo dos mínimos (base e quote)."""
        q = Decimal(str(qty))
        q = (q / self.base_step).to_integral_value(rounding=ROUND_DOWN) * self.base_step
        q = min(q, (self.max_order_size / self.base_step).to_integral_value(ROUND_DOWN) * self.base_step)
        if not self.active or q < self.min_order_size or q * Decimal(str(price)) < self.min_order_size_quote:
            return Decimal(0)
        return q.normalize() if q != 0 else Decimal(0)

    def quantize_price(self, price: float | Decimal) -> Decimal:
        p = Decimal(str(price))
        return (p / self.quote_step).to_integral_value(rounding=ROUND_DOWN) * self.quote_step


DEFAULT_RULES = PairRules(Decimal("0.00000001"), Decimal("0.01"), Decimal("0.00000001"), Decimal("1e18"), Decimal("1"))


def pairs_to_rules(pairs: dict) -> dict[str, PairRules]:
    """Resposta usa 'BTC/USD'; pedidos usam 'BTC-USD' (docs: symbol format difference)."""
    return {k.replace("/", "-"): PairRules.from_api(v) for k, v in pairs.items()}
