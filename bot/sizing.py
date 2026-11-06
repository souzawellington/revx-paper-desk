"""EV e Quarter-Kelly — fórmulas literais do PDF."""
from __future__ import annotations
from dataclasses import dataclass


class InsufficientData(Exception):
    """PDF Hallucination Pruning -> INSUFFICIENT_DATA."""


def expected_value(p: float, r_w: float, r_l: float, c: float) -> float:
    """EV = p*R_w - q*R_l - C"""
    return p * r_w - (1 - p) * r_l - c


def full_kelly(p: float, b: float) -> float:
    """f* = (b*p - q)/b"""
    if b is None or p is None or b <= 0 or not 0 <= p <= 1:
        raise InsufficientData("p ou b ausente/inválido")
    return (b * p - (1 - p)) / b


@dataclass
class SizingResult:
    p: float
    b: float
    full_kelly: float
    quarter_kelly: float
    allocation: float  # após (1-alpha), multiplicador de risco e teto 15%


def size_position(p, avg_win, avg_loss, cfg, risk_multiplier: float = 1.0, alpha: float = 0.0) -> SizingResult:
    if avg_win is None or avg_loss is None or avg_loss <= 0 or avg_win <= 0:
        raise InsufficientData("R_w/R_l indisponível para b")
    b = avg_win / avg_loss
    f = full_kelly(p, b)
    q = f * cfg.kelly_fraction  # f*/4
    alloc = max(0.0, q) * (1 - max(cfg.overfit_alpha, alpha)) * risk_multiplier  # (1-alpha) do PDF
    alloc = min(alloc, cfg.max_position_fraction)
    return SizingResult(p, b, f, q, alloc)
