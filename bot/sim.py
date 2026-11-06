"""Feeds sintéticos (cripto: vol mais alta) determinísticos para demo/testes (sem rede)."""
import math, random, time
from .signals import Bars, SignalHistory


class SyntheticMarket:
    def __init__(self, tickers, seed=7, drift=0.006, vol=0.02):
        rnd = random.Random(seed); self.series = {}
        for t in tickers:
            px, out = 100.0, []
            for _ in range(80):
                px *= 1 + drift + rnd.gauss(0, vol); out.append(px)
            self.series[t] = out
        self.shock = {}

    def bars(self, t):
        c = self.series[t]
        vol = [1e6] * (len(c) - 1) + [2e6]
        return Bars([x * 1.01 for x in c], [x * 0.99 for x in c], c, vol, time.time())

    def last_price(self, t): return self.series[t][-1] * self.shock.get(t, 1.0)


class NullSentiment:
    def score(self, t): return None
    def macro(self): return None


class FixedStats:
    def __init__(self, n=100, wins=58, avg_win=2.0, avg_loss=1.0):
        self.h = SignalHistory(n, wins, avg_win, avg_loss)
    def get(self, t): return self.h
