"""Motor de sinal quantificável: momentum técnico + macro/sentimento como inputs numéricos.
Texto social NUNCA entra aqui — apenas scores numéricos (Prompt Injection Shield)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence
from .indicators import atr, sma
from .sizing import InsufficientData


@dataclass
class Bars:
    high: Sequence[float]
    low: Sequence[float]
    close: Sequence[float]
    volume: Sequence[float]
    timestamp: float  # epoch do último bar


@dataclass
class SignalHistory:
    """Estatística empírica de sinais análogos (passo 1 do PDF). Fonte: ledger do backtest (bot/backtest.py).
    avg_win/avg_loss em múltiplos de R (R = risco inicial até ao stop ATR) -> b = avg_win/avg_loss."""
    n: int
    wins: int
    avg_win: float
    avg_loss: float
    alpha: float = 0.0   # taxa de sobreajuste estimada (IS vs OOS)


@dataclass
class Signal:
    ticker: str
    active: bool
    momentum_confidence: float
    volume_confirmed: bool
    atr: float
    stop_price: float
    p: float
    avg_win: float
    avg_loss: float
    sentiment: float
    reason: str


def technical_state(high, low, close, volume, cfg):
    """Regras técnicas PURAS, partilhadas por bot ao vivo e backtest (sem look-ahead: usa só o passado fornecido).
    Devolve (trend, momentum_conf, volume_confirmed, vol_ratio, atr, stop_atr)."""
    a = atr(high, low, close, cfg.atr_period)
    fast, slow = sma(close, 20), sma(close, 50)
    vavg = sma(volume, 20)
    vol_ratio = volume[-1] / vavg if vavg > 0 else 0.0
    volume_confirmed = vol_ratio >= cfg.volume_confirm_ratio
    trend = close[-1] > fast > slow
    strength = min(1.0, max(0.0, (close[-1] - slow) / (cfg.atr_stop_multiplier * a * 5))) if a > 0 else 0.0
    momentum_conf = strength if trend else 0.0
    stop = close[-1] - cfg.atr_stop_multiplier * a
    return trend and momentum_conf > 0, momentum_conf, volume_confirmed, vol_ratio, a, stop


def compute_signal(ticker: str, bars: Bars, hist: Optional[SignalHistory], sentiment: Optional[float],
                   macro_score: Optional[float], cfg, now: float) -> Signal:
    if now - bars.timestamp > cfg.max_data_staleness_s:
        raise InsufficientData("dados de mercado obsoletos")
    if hist is None or hist.n < cfg.min_signal_samples:
        raise InsufficientData("amostra empírica de p insuficiente")
    c = bars.close
    trend, momentum_conf, volume_confirmed, vol_ratio, a, stop = technical_state(bars.high, bars.low, c, bars.volume, cfg)
    p = hist.wins / hist.n
    sent = 0.0 if sentiment is None else max(-1.0, min(1.0, sentiment))
    # PDF alpha_strategy: penalização severa a narrativa social sem confirmação de volume.
    # Sentimento/macro apenas modulam p de forma limitada; sem volume, o efeito é descontado.
    adj = 0.02 * sent + 0.02 * (macro_score or 0.0)
    if not volume_confirmed:
        adj = min(adj, 0.0) + max(adj, 0.0) * cfg.social_unconfirmed_discount
    p = max(0.0, min(1.0, p + adj))
    return Signal(ticker, trend, momentum_conf, volume_confirmed, a, stop,
                  p, hist.avg_win, hist.avg_loss, sent,
                  f"active={trend} vol_ratio={vol_ratio:.2f} atr={a:.4f}")
