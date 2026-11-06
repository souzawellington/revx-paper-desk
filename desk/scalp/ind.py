"""Indicadores INCREMENTAIS e serializáveis (estado = dict JSON) para os bots Scalp. Mesmo código no replay e no forward.
Wilder (RMA) para RSI/ATR/ADX; BB = média e desvio-padrão populacional (ddof=0) dos últimos n fechos.
"""
from __future__ import annotations
import math


class EMA:
    def __init__(self, n, s=None):
        self.n, self.a = n, 2.0 / (n + 1); s = s or {}
        self.v, self.k = s.get("v"), s.get("k", 0)

    def update(self, x):
        self.v = x if self.v is None else self.v + self.a * (x - self.v); self.k += 1; return self.v

    @property
    def ready(self): return self.k >= self.n

    def dump(self): return {"v": self.v, "k": self.k}


class RMA:
    """Média de Wilder: semente = média simples dos primeiros n valores."""
    def __init__(self, n, s=None):
        self.n = n; s = s or {}
        self.v, self.k, self.acc = s.get("v"), s.get("k", 0), s.get("acc", 0.0)

    def update(self, x):
        self.k += 1
        if self.k <= self.n:
            self.acc += x
            if self.k == self.n: self.v = self.acc / self.n
        else:
            self.v = (self.v * (self.n - 1) + x) / self.n
        return self.v

    @property
    def ready(self): return self.k >= self.n

    def dump(self): return {"v": self.v, "k": self.k, "acc": self.acc}


class Window:
    def __init__(self, n, s=None):
        self.n = n; self.x = list((s or {}).get("x", []))

    def push(self, v):
        self.x.append(v)
        if len(self.x) > self.n: self.x.pop(0)

    @property
    def full(self): return len(self.x) >= self.n

    def dump(self): return {"x": self.x}


class TFInd:
    """Todos os indicadores de UM símbolo num timeframe. update(bar) devolve o dicionário de valores DEPOIS da barra.
    Valores "prev_*" (janelas de range/volume) excluem a barra actual."""
    def __init__(self, P, s=None):
        s = s or {}; self.P = P
        self.pc = s.get("pc")
        self.bb = Window(P["bb_n"], s.get("bb"))
        self.rsi_g, self.rsi_l = RMA(P["rsi_n"], s.get("rsi_g")), RMA(P["rsi_n"], s.get("rsi_l"))
        self.atr = RMA(P["atr_n"], s.get("atr"))
        self.e_fast, self.e_slow = EMA(P["ema_fast"], s.get("e_fast")), EMA(P["ema_slow"], s.get("e_slow"))
        self.pdm, self.mdm, self.tr = RMA(P["adx_n"], s.get("pdm")), RMA(P["adx_n"], s.get("mdm")), RMA(P["adx_n"], s.get("tr"))
        self.adx = RMA(P["adx_n"], s.get("adx"))
        self.hi, self.lo = Window(P["range_n"], s.get("hi")), Window(P["range_n"], s.get("lo"))
        self.vol = Window(P["vol_n"], s.get("vol"))
        self.ph, self.pl = s.get("ph"), s.get("pl")
        self.n = s.get("n", 0)

    def dump(self):
        return {"pc": self.pc, "bb": self.bb.dump(), "rsi_g": self.rsi_g.dump(), "rsi_l": self.rsi_l.dump(), "atr": self.atr.dump(),
                "e_fast": self.e_fast.dump(), "e_slow": self.e_slow.dump(), "pdm": self.pdm.dump(), "mdm": self.mdm.dump(),
                "tr": self.tr.dump(), "adx": self.adx.dump(), "hi": self.hi.dump(), "lo": self.lo.dump(), "vol": self.vol.dump(),
                "ph": self.ph, "pl": self.pl, "n": self.n}

    def update(self, b):
        o, h, l, c, v = b["o"], b["h"], b["l"], b["c"], b["v"]
        out = {"prev_range_hi": max(self.hi.x) if self.hi.full else None, "prev_range_lo": min(self.lo.x) if self.lo.full else None,
               "prev_vol_avg": (sum(self.vol.x) / len(self.vol.x)) if self.vol.full else None}
        self.n += 1
        if self.pc is not None:
            d = c - self.pc; self.rsi_g.update(max(d, 0.0)); self.rsi_l.update(max(-d, 0.0))
            tr = max(h - l, abs(h - self.pc), abs(l - self.pc))
            up, dn = h - self.ph, self.pl - l
            pdm = up if (up > dn and up > 0) else 0.0; mdm = dn if (dn > up and dn > 0) else 0.0
            self.atr.update(tr); self.pdm.update(pdm); self.mdm.update(mdm); self.tr.update(tr)
            if self.tr.ready:
                trv = self.tr.v or 0.0
                dip = 100 * self.pdm.v / trv if trv > 0 else 0.0; dim = 100 * self.mdm.v / trv if trv > 0 else 0.0
                dx = 100 * abs(dip - dim) / (dip + dim) if (dip + dim) > 0 else 0.0
                self.adx.update(dx)
        self.bb.push(c); self.e_fast.update(c); self.e_slow.update(c)
        self.hi.push(h); self.lo.push(l); self.vol.push(v)
        self.pc, self.ph, self.pl = c, h, l
        if self.bb.full:
            m = sum(self.bb.x) / len(self.bb.x); sd = math.sqrt(sum((x - m) ** 2 for x in self.bb.x) / len(self.bb.x))
            out.update(bb_mid=m, bb_lo=m - self.P["bb_k"] * sd, bb_hi=m + self.P["bb_k"] * sd)
        if self.rsi_g.ready:
            g, ls = self.rsi_g.v, self.rsi_l.v
            out["rsi"] = 50.0 if (g == 0 and ls == 0) else (100.0 if ls == 0 else 100 - 100 / (1 + g / ls))
        if self.atr.ready: out["atr"] = self.atr.v
        if self.e_slow.ready: out.update(ema_fast=self.e_fast.v, ema_slow=self.e_slow.v)
        if self.adx.ready: out["adx"] = self.adx.v
        out["ready"] = self.n >= self.P["warmup_bars"] and all(k in out for k in ("bb_mid", "rsi", "atr", "ema_slow", "adx"))
        return out
