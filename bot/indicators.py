from __future__ import annotations
from typing import Sequence


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], n: int) -> float:
    if len(close) < n + 1:
        raise ValueError("histórico insuficiente para ATR")
    trs = [max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
           for i in range(1, len(close))]
    return sum(trs[-n:]) / n


def sma(x: Sequence[float], n: int) -> float:
    if len(x) < n:
        raise ValueError("histórico insuficiente para SMA")
    return sum(x[-n:]) / n
