"""Feeds. Mercado: endpoints PÚBLICOS Revolut X (sem auth).
Sentimento/macro/estatísticas: PLACEHOLDERS (só números)."""
from __future__ import annotations
import json, os, time
from typing import Optional
from .signals import Bars, SignalHistory


class RevolutXMarketFeed:
    def __init__(self, client, cfg):
        self.c, self.cfg, self._px, self._px_t = client, cfg, {}, 0.0

    def bars(self, symbol: str) -> Bars:
        iv = self.cfg.candle_interval_min
        until = int(time.time() * 1000)
        since = until - iv * 60_000 * self.cfg.candle_count   # docs: (until-since)/interval <= 100 em /candles
        rows = sorted(self.c.public_candles(symbol, iv, since, until, self.cfg.region), key=lambda r: r["start"])
        rows = [r for r in rows if r["start"] + iv * 60_000 <= until]  # descarta candle em formação
        f = lambda k: [float(r[k]) for r in rows]
        # timestamp = FIM do último candle (start + intervalo)
        last = (rows[-1]["start"] / 1000 + iv * 60) if rows else 0
        return Bars(f("high"), f("low"), f("close"), f("volume"), last)

    def last_price(self, symbol: str) -> float:
        if time.time() - self._px_t > 5:
            data = self.c.public_tickers(self.cfg.symbols, self.cfg.region)
            px = {}
            for t in data:
                if self.cfg.region and t.get("region") not in (None, self.cfg.region): continue
                px.setdefault(t["symbol"].replace("/", "-"), float(t["mid"]))
            self._px, self._px_t = px, time.time()
        if symbol not in self._px:
            raise KeyError(f"sem ticker para {symbol}")
        return self._px[symbol]


class SentimentFeed:
    def score(self, symbol: str) -> Optional[float]: return None   # PLACEHOLDER [-1,1]
    def macro(self) -> Optional[float]: return None                # PLACEHOLDER [-1,1]


class SignalStatsStore:
    """Lê o ledger do backtest (python -m bot.backtest). Ledger ausente, antigo, de outra configuração
    ou com n < min_signal_samples -> InsufficientData (o engine converte em HOLD INSUFFICIENT_DATA)."""
    def __init__(self, cfg=None, path: Optional[str] = None, now=time.time):
        from .config import Config
        self.cfg = cfg or Config()
        self.path = path or self.cfg.ledger_path
        self.now = now

    def _load(self) -> dict:
        from .sizing import InsufficientData
        if not os.path.exists(self.path):
            raise InsufficientData("ledger de estatísticas ausente (corra python -m bot.backtest)")
        led = json.load(open(self.path))
        age_d = (self.now() - float(led.get("generated_at", 0))) / 86400
        if age_d > self.cfg.ledger_max_age_days:
            raise InsufficientData(f"ledger com {age_d:.1f} dias (> {self.cfg.ledger_max_age_days})")
        from .backtest import fingerprint
        if led.get("config") != fingerprint(self.cfg):
            raise InsufficientData("ledger gerado com parâmetros diferentes dos atuais")
        return led

    def get(self, symbol: str) -> Optional[SignalHistory]:
        from .sizing import InsufficientData
        s = self._load()["symbols"].get(symbol)
        if not s:
            raise InsufficientData(f"sem estatísticas para {symbol} no ledger")
        if s["n"] < self.cfg.min_signal_samples:
            raise InsufficientData(f"n={s['n']} < {self.cfg.min_signal_samples} trades fora-da-amostra")
        return SignalHistory(int(s["n"]), int(s["wins"]), float(s["avg_win"]), float(s["avg_loss"]), float(s.get("alpha", 0.0)))
