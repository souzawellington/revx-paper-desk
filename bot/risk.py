"""Drawdown de carteira em tempo real + hard-stop por posição (-8% entrada/pico)."""
from __future__ import annotations
from enum import Enum


class RiskMode(str, Enum):
    NORMAL = "NORMAL"
    REDUCE = "REDUCE"
    SUSPEND = "SUSPEND"


class DrawdownMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.peak = None
        self.max_dd = 0.0
        self.mode = RiskMode.NORMAL

    def update(self, equity: float) -> RiskMode:
        self.peak = equity if self.peak is None else max(self.peak, equity)
        dd = (self.peak - equity) / self.peak if self.peak > 0 else 0.0  # |MDD| do PDF
        self.current_dd = dd
        self.max_dd = max(self.max_dd, dd)
        if dd >= self.cfg.portfolio_dd_suspend:
            self.mode = RiskMode.SUSPEND
        elif dd >= self.cfg.portfolio_dd_reduce:
            self.mode = RiskMode.REDUCE if self.mode != RiskMode.SUSPEND else RiskMode.SUSPEND
        elif self.mode != RiskMode.SUSPEND:
            self.mode = RiskMode.NORMAL
        # SUSPEND é "latched": só reset manual (ver GAPS.md)
        return self.mode

    def risk_multiplier(self) -> float:
        return {RiskMode.NORMAL: 1.0, RiskMode.REDUCE: self.cfg.reduce_size_multiplier,
                RiskMode.SUSPEND: 0.0}[self.mode]

    def reset(self):
        self.mode = RiskMode.NORMAL
        self.peak = None


def position_stop_hit(entry: float, local_peak: float, price: float, atr_stop: float | None, cfg) -> str | None:
    ref = max(entry, local_peak)
    if price <= ref * (1 - cfg.position_hard_stop_pct):
        return "HARD_STOP_8PCT"
    if atr_stop is not None and price <= atr_stop:
        return "ATR_STOP"
    return None
