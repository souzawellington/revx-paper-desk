"""Motor determinístico dos bots Scalp (paper). Aritmética pura sobre velas 1m: sem broker, sem rede, sem chaves.
O MESMO motor corre o REPLAY e o FORWARD; o estado (indicadores, livros, pendentes) é um dict JSON serializável.
step(ts, bars) processa um minuto (todas as moedas) — ver ordem das fases em `step`.
"""
from __future__ import annotations
import math
from .ind import TFInd
from .spec import SPEC

M1 = 60_000
D = 86_400_000
EX, RK, BOTS, RG = SPEC["execution"], SPEC["risk"], SPEC["bots"], SPEC["regime"]
SYMS = SPEC["symbols"]
BOOKS = [b for k in BOTS for b in (k, k + "_adx")]
BROKER = None   # deliberado: nunca há broker aqui


def bot_of(book): return book[:-4] if book.endswith("_adx") else book


def new_book(eq=None):
    eq = RK["start_equity"] if eq is None else eq
    return {"cash": eq, "equity": eq, "peak": eq, "max_dd": 0.0, "day": None, "day_open": eq, "halted_until": None,
            "killed": None, "ceiling": None, "pos": {}, "pend": {}, "seq": 0,
            "n": {"signals": 0, "rej_cost": 0, "rej_regime": 0, "rej_busy": 0, "rej_cash": 0, "placed": 0, "unfilled": 0, "filled": 0,
                  "halts": 0}}


def new_state(trade_from=0):
    return {"spec_id": SPEC["id"], "trade_from": trade_from, "last_ts": None, "last_close": {},
            "ind": {s: {"1": None, "5": None} for s in SYMS}, "agg5": {s: None for s in SYMS}, "last5": {s: None for s in SYMS},
            "books": {b: new_book() for b in BOOKS}}


class Engine:
    def __init__(self, state, half_spread, on_trade=None, on_event=None, catchup=False):
        self.st = state; self.hs = half_spread; self.on_trade = on_trade or (lambda t: None); self.on_event = on_event or (lambda e: None)
        self.catchup = catchup
        P = SPEC["indicators"]
        self.ind = {s: {tf: TFInd(P, state["ind"][s][tf]) for tf in ("1", "5")} for s in SYMS}

    def dump(self):
        for s in SYMS:
            for tf in ("1", "5"): self.st["ind"][s][tf] = self.ind[s][tf].dump()
        return self.st

    # ---------- custos ----------
    def _taker_exit(self, b, sym, ref, ts, why, p):
        hs = self.hs(sym, ts); px = ref * (1 - EX["slippage"] - hs)
        fee = p["qty"] * px * EX["taker_fee"]; slip = p["qty"] * ref * (EX["slippage"] + hs)
        self._close(b, sym, p, px, fee, slip, ts, why)

    def _close(self, b, sym, p, px, fee, slip, ts, why):
        pnl = p["qty"] * (px - p["entry"]) - fee
        b["cash"] += p["qty"] * px - fee
        del b["pos"][sym]
        t = {"book": b["_name"], "symbol": sym, "signal_ts": p["signal_ts"], "fill_ts": p["fill_ts"], "exit_ts": ts,
             "entry": p["entry"], "stop": p["stop"], "tp": p["tp"], "stop_pct": p["d"], "qty": p["qty"], "notional": p["qty"] * p["entry"],
             "exit": px, "reason": why, "fee": fee, "slip_cost": slip, "pnl": pnl, "r_unit": p["r_unit"],
             "r": pnl / p["r_unit"] if p["r_unit"] > 0 else 0.0, "catchup": bool(p.get("catchup") or self.catchup)}
        self.on_trade(t)

    # ---------- um minuto ----------
    def step(self, ts, bars):
        """bars: {sym: {o,h,l,c,v}} para o minuto `ts` (início da vela). Fases:
        1 dia UTC novo → reabre dia / levanta halt; 2 pendentes: enchem se low < limite (se o mesmo low ≤ stop → stop);
        3 posições: stop (taker) > alvo (maker); 4 indicadores 1m (+5m na fronteira); 5 saídas de estratégia/tempo ao fecho do tf;
        6 marcação, pico/DD, kill diário −2%, kill DD 20%, teto $1000; 7 sinais novos → limites post-only."""
        st = self.st
        if st["last_ts"] is not None and ts <= st["last_ts"]: return
        day = ts // D
        for name, b in st["books"].items():
            b["_name"] = name
            if b["day"] != day:
                b["day"] = day; b["day_open"] = b["equity"]
                if b["halted_until"] is not None and day >= b["halted_until"]: b["halted_until"] = None
        # 2 + 3
        for name, b in st["books"].items():
            for sym, bar in bars.items():
                q = b["pend"].get(sym)
                if q:
                    if ts >= q["expiry"]:
                        b["cash"] += q["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
                    elif bar["l"] < q["limit"]:
                        b["cash"] += q["reserve"] - q["qty"] * q["limit"]; del b["pend"][sym]; b["n"]["filled"] += 1
                        p = {**q, "entry": q["limit"], "fill_ts": ts, "bars_held": 0, "catchup": self.catchup}
                        b["pos"][sym] = p
                        if bar["l"] <= p["stop"]:
                            self._taker_exit(b, sym, p["stop"], ts, "stop (mesma vela da entrada)", p)
                        continue
                p = b["pos"].get(sym)
                if p and p["fill_ts"] < ts:
                    if bar["l"] <= p["stop"]:
                        self._taker_exit(b, sym, min(p["stop"], bar["o"]), ts, "stop", p)
                    elif bar["h"] > p["tp"]:
                        self._close(b, sym, p, p["tp"], 0.0, 0.0, ts, "alvo (maker)")
        # 4
        sig = {}
        for sym, bar in bars.items():
            st["last_close"][sym] = bar["c"]
            v1 = self.ind[sym]["1"].update(bar); sig[(sym, 1)] = (v1, bar)
            a = st["agg5"][sym]
            if a is None or a["ts"] != ts - ts % (5 * M1):
                a = {"ts": ts - ts % (5 * M1), "o": bar["o"], "h": bar["h"], "l": bar["l"], "c": bar["c"], "v": bar["v"]}
            else:
                a = {**a, "h": max(a["h"], bar["h"]), "l": min(a["l"], bar["l"]), "c": bar["c"], "v": a["v"] + bar["v"]}
            st["agg5"][sym] = a
            if (ts + M1) % (5 * M1) == 0:
                v5 = self.ind[sym]["5"].update(a); sig[(sym, 5)] = (v5, a); st["agg5"][sym] = None
        # 5
        for name, b in st["books"].items():
            bot = bot_of(name); S = BOTS[bot]; tf = S["tf"]
            for sym in list(b["pos"]):
                if (sym, tf) not in sig: continue
                p = b["pos"][sym]
                v, bar = sig[(sym, tf)]
                p["bars_held"] += 1
                why = self._short_exit(bot, v, bar)
                if why: self._taker_exit(b, sym, bar["c"], ts, why, p)
                elif p["bars_held"] >= S["time_stop_bars"]: self._taker_exit(b, sym, bar["c"], ts, f"tempo ({S['time_stop_bars']} velas)", p)
        # 6
        for name, b in st["books"].items():
            eq = b["cash"] + sum(q["reserve"] for q in b["pend"].values()) + \
                 sum(p["qty"] * st["last_close"].get(s, p["entry"]) for s, p in b["pos"].items())
            b["equity"] = eq; b["peak"] = max(b["peak"], eq); b["max_dd"] = max(b["max_dd"], 1 - eq / b["peak"] if b["peak"] else 0)
            if b["killed"] or b["ceiling"]: continue
            if eq >= RK["ceiling"]:
                self._flatten(b, ts, "teto $1.000"); b["ceiling"] = ts
                self.on_event({"type": "ceiling", "book": name, "ts": ts, "equity": b["equity"]})
            elif 1 - eq / b["peak"] > RK["dd_kill"]:
                self._flatten(b, ts, "kill DD>20%"); b["killed"] = ts
                self.on_event({"type": "dd_kill", "book": name, "ts": ts, "equity": b["equity"], "peak": b["peak"]})
            elif b["halted_until"] is None and eq <= b["day_open"] * (1 - RK["daily_kill"]):
                self._flatten(b, ts, "kill diário −2%"); b["halted_until"] = day + 1; b["n"]["halts"] += 1
                self.on_event({"type": "daily_kill", "book": name, "ts": ts, "equity": b["equity"], "day_open": b["day_open"]})
        # 7
        if ts >= st["trade_from"]:
            for name, b in st["books"].items():
                if b["killed"] or b["ceiling"] or b["halted_until"] is not None: continue
                bot = bot_of(name); S = BOTS[bot]; tf = S["tf"]
                for sym in SYMS:
                    if (sym, tf) not in sig: continue
                    v, bar = sig[(sym, tf)]
                    if not v.get("ready") or not self._entry(bot, v, bar): continue
                    b["n"]["signals"] += 1
                    if name.endswith("_adx") and not self._regime_ok(bot, v): b["n"]["rej_regime"] += 1; continue
                    if sym in b["pos"] or sym in b["pend"] or len(b["pos"]) + len(b["pend"]) >= RK["max_open"]:
                        b["n"]["rej_busy"] += 1; continue
                    self._place(b, sym, bot, v, bar, ts, tf)
        st["last_ts"] = ts

    def _flatten(self, b, ts, why):
        for sym in list(b["pend"]):
            b["cash"] += b["pend"][sym]["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
        for sym in list(b["pos"]):
            self._taker_exit(b, sym, self.st["last_close"][sym], ts, why, b["pos"][sym])
        b["equity"] = b["cash"]

    # ---------- regras de sinal (congeladas no SPEC) ----------
    @staticmethod
    def _entry(bot, v, bar):
        c = bar["c"]
        if bot == "bb_rsi":
            return c < v["bb_lo"] and v["rsi"] < BOTS[bot]["rsi_max"]
        if bot == "ema_pb":
            rng = bar["h"] - bar["l"]; wick = min(bar["o"], c) - bar["l"]
            return (v["ema_fast"] > v["ema_slow"] and bar["l"] <= v["ema_fast"] and c > v["ema_fast"] and c > v["ema_slow"]
                    and rng > 0 and wick >= BOTS[bot]["wick_min"] * rng)
        if bot == "brk":
            hi, lo, va = v["prev_range_hi"], v["prev_range_lo"], v["prev_vol_avg"]
            if hi is None or lo is None or va is None or lo <= 0: return False
            return hi / lo - 1 < BOTS[bot]["range_max"] and c > hi and bar["v"] > 0 and bar["v"] > BOTS[bot]["vol_mult"] * va
        return False

    @staticmethod
    def _short_exit(bot, v, bar):
        """Sinal 'curto' / invalidação → sai do long existente (nunca abre short: spot only)."""
        c = bar["c"]
        if bot == "bb_rsi" and "bb_hi" in v and "rsi" in v and c > v["bb_hi"] and v["rsi"] > BOTS[bot]["rsi_short"]:
            return "sinal curto (BB alta + RSI>75) → sai"
        if bot == "ema_pb" and "ema_slow" in v and (c < v["ema_slow"] or v["ema_fast"] < v["ema_slow"]):
            return "sinal curto (abaixo EMA21 / EMA9<EMA21) → sai"
        if bot == "brk" and v.get("prev_range_lo") is not None and c < v["prev_range_lo"]:
            return "sinal curto (fecho abaixo do range) → sai"
        return None

    @staticmethod
    def _regime_ok(bot, v):
        return v["adx"] < RG["adx_mr_max"] if bot == "bb_rsi" else v["adx"] > RG["adx_trend_min"]

    def _place(self, b, sym, bot, v, bar, ts, tf):
        L = bar["c"]; hs = self.hs(sym, ts)
        d = min(RK["stop_fixed"], RK["stop_atr_mult"] * v["atr"] / L) if L > 0 else 0.0
        tp = L * (1 + RK["rr_min"] * d)
        if bot == "bb_rsi": tp = max(v["bb_mid"], tp)
        cost_rt = EX["taker_fee"] + EX["slippage"] + 2 * hs
        if d <= 0 or tp / L - 1 <= cost_rt:
            b["n"]["rej_cost"] += 1; return
        stop = L * (1 - d)
        per_unit = (L - stop) + stop * (EX["taker_fee"] + EX["slippage"] + hs)
        qty = RK["risk_pct"] * b["equity"] / per_unit
        cap = min(RK["pos_cap_frac"] * b["equity"], b["cash"])
        if cap <= 0.1: b["n"]["rej_cash"] += 1; return            # mínimo Revolut X: 0,10 USD
        qty = min(qty, cap / L)
        b["seq"] += 1; b["n"]["placed"] += 1
        bar_close = ts + M1
        b["pend"][sym] = {"id": b["seq"], "limit": L, "qty": qty, "reserve": qty * L, "stop": stop, "tp": tp, "d": d,
                          "r_unit": qty * per_unit, "signal_ts": bar_close, "expiry": bar_close + EX["entry_valid_bars"] * tf * M1,
                          "atr": v["atr"], "adx": v.get("adx")}
        b["cash"] -= qty * L


def metrics(trades, book_state=None):
    A = SPEC["auditor"]; n = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]; losses = [-t["pnl"] for t in trades if t["pnl"] <= 0]
    rs = [t["r"] for t in trades]
    exp = sum(rs) / n if n else None; wr = len(wins) / n if n else None
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (math.inf if wins else None)
    dd = (book_state or {}).get("max_dd", 0.0)
    if n < A["min_trades"]:
        verdict = "NO-GO (DD>20% já com poucos trades)" if dd > A["max_dd"] else "dados insuficientes"
    elif wr >= A["win_rate"] and exp >= A["expectancy_r"] and dd <= A["max_dd"]:
        verdict = "possível GO (só paper)"
    else:
        verdict = "NO-GO"
    return {"trades": n, "win_rate": wr, "expectancy_r": exp, "profit_factor": pf, "max_dd": dd,
            "fees": sum(t["fee"] for t in trades), "slippage_spread": sum(t["slip_cost"] for t in trades),
            "pnl": sum(t["pnl"] for t in trades), "avg_stop_pct": (sum(t["stop_pct"] for t in trades) / n) if n else None,
            "avg_notional": (sum(t["notional"] for t in trades) / n) if n else None,
            "reasons": {r: sum(1 for t in trades if t["reason"].split(" (")[0].split(" →")[0] == r)
                        for r in sorted({t["reason"].split(" (")[0].split(" →")[0] for t in trades})},
            "verdict": verdict}
