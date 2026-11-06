"""Indicadores INCREMENTAIS e serializáveis (estado = dict JSON) dos livros EMS. Só usam velas JÁ FECHADAS.
Floats de propósito: decidem, não contam dinheiro. RSI/ATR = Wilder (RMA, reaproveitado de desk/scalp/ind.py)."""
from __future__ import annotations
import math
from desk.scalp.ind import RMA, Window


class EMSInd:
    def __init__(self, P, s=None):
        s = s or {}; self.P = P
        self.pc = s.get("pc"); self.n = s.get("n", 0)
        self.rsi_g, self.rsi_l = RMA(P["rsi_n"], s.get("rsi_g")), RMA(P["rsi_n"], s.get("rsi_l"))
        self.atr = RMA(P["atr_n"], s.get("atr"))
        self.bb = Window(P["bb_n"], s.get("bb"))
        self.widths = Window(P["squeeze_lookback"] + 1, s.get("widths"))   # larguras até à vela ANTERIOR
        self.vw = Window(P["vwap_n"], s.get("vw"))                         # [preço típico × v, v]
        self.vol = Window(P["vol_n"], s.get("vol"))
        self.div = Window(P["div_lookback"], s.get("div"))                 # [low, rsi] das velas anteriores

    def dump(self):
        return {"pc": self.pc, "n": self.n, "rsi_g": self.rsi_g.dump(), "rsi_l": self.rsi_l.dump(), "atr": self.atr.dump(),
                "bb": self.bb.dump(), "widths": self.widths.dump(), "vw": self.vw.dump(), "vol": self.vol.dump(), "div": self.div.dump()}

    def update(self, b):
        P = self.P
        o, h, l, c, v = b["o"], b["h"], b["l"], b["c"], b["v"]
        out = {"open": o, "close": c, "low": l, "high": h, "vol": v,
               "prev_vol_avg": (sum(self.vol.x) / len(self.vol.x)) if self.vol.full else None}
        # micro-divergência: mínimo das velas ANTERIORES (exclui a actual)
        if self.div.full:
            j = min(range(len(self.div.x)), key=lambda i: self.div.x[i][0])
            out["div_low"], out["div_rsi"] = self.div.x[j][0], self.div.x[j][1]
        # squeeze: largura da vela anterior vs percentil das 120 antes dela
        if self.widths.full:
            prev_w = self.widths.x[-1]; hist = sorted(self.widths.x[:-1])
            out["squeeze_prev"] = prev_w <= hist[int(len(hist) * P["squeeze_pct"])]
        self.n += 1
        out["ret_bps"] = (c / self.pc - 1) * 1e4 if self.pc else 0.0
        if self.pc is not None:
            d = c - self.pc; self.rsi_g.update(max(d, 0.0)); self.rsi_l.update(max(-d, 0.0))
            self.atr.update(max(h - l, abs(h - self.pc), abs(l - self.pc)))
        self.bb.push(c); self.vol.push(v); self.vw.push([(h + l + c) / 3 * v, v])
        self.pc = c
        if self.bb.full:
            m = sum(self.bb.x) / len(self.bb.x); sd = math.sqrt(sum((x - m) ** 2 for x in self.bb.x) / len(self.bb.x))
            out.update(bb_mid=m, bb_lo=m - P["bb_k"] * sd, bb_hi=m + P["bb_k"] * sd)
            self.widths.push(4 * sd / m * 1e4 if m else 0.0)
        if self.rsi_g.ready:
            g, ls = self.rsi_g.v, self.rsi_l.v
            out["rsi"] = 50.0 if (g == 0 and ls == 0) else (100.0 if ls == 0 else 100 - 100 / (1 + g / ls))
        if self.atr.ready: out["atr_bps"] = self.atr.v / c * 1e4 if c else 0.0
        if self.vw.full:
            sv = sum(x[1] for x in self.vw.x)
            out["vwap"] = sum(x[0] for x in self.vw.x) / sv if sv > 0 else None
        if "rsi" in out: self.div.push([l, out["rsi"]])
        out["ready"] = self.n >= P["warmup_bars"] and all(k in out for k in ("bb_mid", "rsi", "atr_bps", "squeeze_prev", "div_low")) \
            and out.get("prev_vol_avg") is not None
        return out
