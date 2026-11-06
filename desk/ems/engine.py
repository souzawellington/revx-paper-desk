"""Motor determinístico dos livros EMS (paper). Velas 1m fechadas, sem rede, sem broker, sem chaves.
Dinheiro (caixa, preços de execução, quantidades, taxas, PnL) em Decimal; indicadores em float (só decidem).
O estado é um dict JSON (Decimais gravados como texto). step(ts, bars, ctx) processa um minuto de todas as moedas.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from .ind import EMSInd
from .spec import SPEC

M1 = 60_000
DAY = 86_400_000
D = Decimal
EX, RK, BK, FL, IND = SPEC["execution"], SPEC["risk"], SPEC["books"], SPEC["filters"], SPEC["indicators"]
SYMS = SPEC["symbols"]
BOOKS = list(BK)
BROKER = None                     # deliberado: nunca há broker aqui
TRAINING, HALTED, CEILING = "PAPER_TRAINING", "HALTED_MAX_DRAWDOWN", "CEILING_PAUSED"

TAKER, MAKER, SLIP = D(EX["taker_fee"]), D(EX["maker_fee"]), D(EX["slippage"])
START, RISK, CAP, STEP, MIN_NOT = D(RK["start_equity"]), D(RK["risk_pct"]), D(RK["pos_cap_frac"]), D(RK["qty_step"]), D(RK["min_notional"])
DD_KILL, CEIL = D(RK["dd_kill"]), D(RK["ceiling"])
MIN_EDGE = D(str(EX["taker_min_edge"]))
TAKER_RESERVE_BUF = D("1.02")     # reserva p/ entrada taker (abertura pode vir acima do fecho)
MONEY = {"cash", "equity", "peak", "qty", "limit", "entry", "stop", "tp", "reserve", "d", "r_unit", "entry_fee", "equity_before"}


def dec(x) -> Decimal: return x if isinstance(x, Decimal) else D(str(x))


def _conv(o, f):
    if isinstance(o, dict): return {k: (f(v) if k in MONEY and v is not None and not isinstance(v, (dict, list)) else _conv(v, f)) for k, v in o.items()}
    if isinstance(o, list): return [_conv(v, f) for v in o]
    return o


def to_json(st): return _conv(st, str)


def from_json(st): return _conv(st, dec)


def new_book(eq=START):
    eq = dec(eq)
    return {"cash": eq, "equity": eq, "peak": eq, "max_dd": 0.0, "state": TRAINING, "state_since": None,
            "pos": {}, "pend": {}, "cycles": 0,
            "n": {"signals": 0, "placed": 0, "maker": 0, "taker": 0, "filled": 0, "unfilled": 0, "rej_cost": 0, "rej_shock": 0,
                  "rej_macro": 0, "rej_busy": 0, "rej_size": 0, "rej_no_book": 0, "rej_book_filter": 0}}


def new_state(trade_from=0):
    return {"spec_id": SPEC["id"], "trade_from": trade_from, "last_ts": None, "last_close": {},
            "ind": {s: None for s in SYMS}, "shock": {s: 0 for s in SYMS}, "recent": {s: [] for s in SYMS},
            "books": {b: new_book() for b in BOOKS}}


class Ctx:
    """Contexto do minuto: meio-spread, macro ponto-no-tempo, livro L2 (só ao vivo) e flag de catchup."""
    def __init__(self, hs=None, macro=None, book=None, catchup=False):
        self.hs = hs or (lambda sym, ts: D(EX["fallback_half_spread"][sym]))
        self.macro = macro or (lambda close_ts: None)
        self.book = book or (lambda sym, close_ts: None)
        self.catchup = catchup


class Engine:
    def __init__(self, state, on_trade=None, on_event=None):
        self.st = state; self.on_trade = on_trade or (lambda t: None); self.on_event = on_event or (lambda e: None)
        self.ind = {s: EMSInd(IND, state["ind"].get(s)) for s in SYMS}

    def dump(self):
        for s in SYMS: self.st["ind"][s] = self.ind[s].dump()
        return self.st

    # ---------- execução ----------
    def _exit_cost(self, hs): return TAKER + SLIP + hs

    def _taker_exit(self, name, b, sym, ref, ts, why, p, ctx):
        hs = ctx.hs(sym, ts); px = ref * (1 - SLIP - hs)
        fee = p["qty"] * px * TAKER; slip = p["qty"] * ref * (SLIP + hs)
        self._close(name, b, sym, p, px, fee, slip, ts, why, ctx)

    def _close(self, name, b, sym, p, px, fee, slip, ts, why, ctx):
        pnl = p["qty"] * (px - p["entry"]) - fee - p["entry_fee"]
        b["cash"] += p["qty"] * px - fee
        del b["pos"][sym]
        r = pnl / p["r_unit"] if p["r_unit"] > 0 else D(0)
        self.on_trade({"book": name, "symbol": sym, "setup": p["setup"], "entry_kind": p["kind"], "signal_ts": p["signal_ts"],
                       "fill_ts": p["fill_ts"], "exit_ts": ts, "entry": p["entry"], "stop": p["stop"], "tp": p["tp"], "stop_pct": p["d"],
                       "qty": p["qty"], "notional": p["qty"] * p["entry"], "exit": px, "reason": why, "fee": fee + p["entry_fee"],
                       "slip_cost": slip, "pnl": pnl, "r_unit": p["r_unit"], "r": r, "catchup": bool(p.get("catchup") or ctx.catchup)})

    def _fill(self, b, sym, q, px, fee, ts, ctx):
        cost = q["qty"] * px + fee
        if cost > q["reserve"]:                         # taker com gap: encolhe para caber na reserva (nunca usa caixa extra)
            q["qty"] = ((q["reserve"] / (px * (1 + TAKER))) / STEP).to_integral_value(ROUND_DOWN) * STEP
            fee = q["qty"] * px * (TAKER if q["kind"] == "taker" else MAKER); cost = q["qty"] * px + fee
        b["cash"] += q["reserve"] - cost; del b["pend"][sym]; b["n"]["filled"] += 1
        d = q["d"]
        stop, tp = (px * (1 - d), px * (1 + d * D(str(RK["rr"])))) if q["kind"] == "taker" else (q["stop"], q["tp"])
        hs = ctx.hs(sym, ts)
        p = {"setup": q["setup"], "kind": q["kind"], "signal_ts": q["signal_ts"], "fill_ts": ts, "entry": px, "qty": q["qty"],
             "stop": stop, "tp": tp, "d": d, "entry_fee": fee, "bars_held": 0, "catchup": ctx.catchup,
             "r_unit": q["qty"] * (px - stop) + q["qty"] * stop * self._exit_cost(hs) + fee}
        b["pos"][sym] = p
        return p

    # ---------- um minuto ----------
    def step(self, ts, bars, ctx=None):
        """bars: {sym: {o,h,l,c,v}} (floats da API) para o minuto `ts` (início da vela). Fases:
        1 pendentes (expiram / enchem: maker se low < limite, taker na abertura) e saídas stop > alvo;
        2 indicadores; 3 saída por tempo ao fecho; 4 marcação, pico/DD, kill 20%, teto $1.000;
        5 regime (choque, macro) e sinais novos → ordens pendentes (elegíveis só a partir da vela seguinte)."""
        ctx = ctx or Ctx(); st = self.st
        if st["last_ts"] is not None and ts <= st["last_ts"]: return
        B = {s: {k: dec(bar[k]) for k in ("o", "h", "l", "c")} for s, bar in bars.items()}
        # 1
        for name, b in st["books"].items():
            for sym, bar in B.items():
                q = b["pend"].get(sym)
                if q:
                    if ts >= q["expiry"]:
                        b["cash"] += q["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
                    elif ts >= q["active_from"]:
                        hs = ctx.hs(sym, ts)
                        if q["kind"] == "taker":
                            px = bar["o"] * (1 + SLIP + hs); p = self._fill(b, sym, q, px, q["qty"] * px * TAKER, ts, ctx)
                        elif bar["l"] < q["limit"]:
                            p = self._fill(b, sym, q, q["limit"], q["qty"] * q["limit"] * MAKER, ts, ctx)
                        else:
                            continue
                        if bar["l"] <= p["stop"]:
                            self._taker_exit(name, b, sym, p["stop"], ts, "stop (mesma vela da entrada)", p, ctx)
                        continue
                p = b["pos"].get(sym)
                if p and p["fill_ts"] < ts:
                    if bar["l"] <= p["stop"]:
                        self._taker_exit(name, b, sym, min(p["stop"], bar["o"]), ts, "stop", p, ctx)
                    elif bar["h"] > p["tp"]:
                        self._close(name, b, sym, p, p["tp"], p["qty"] * p["tp"] * MAKER, D(0), ts, "alvo (maker)", ctx)
        # 2
        V = {}
        for sym, bar in bars.items():
            st["last_close"][sym] = str(B[sym]["c"])
            V[sym] = self.ind[sym].update(bar)
            rec = st["recent"].setdefault(sym, []); rec.append([ts, bar["o"], bar["h"], bar["l"], bar["c"]]); del rec[:-240]
        # 3
        for name, b in st["books"].items():
            for sym in list(b["pos"]):
                if sym not in B: continue
                p = b["pos"][sym]; p["bars_held"] += 1
                if p["bars_held"] >= BK[name]["time_stop_bars"]:
                    self._taker_exit(name, b, sym, B[sym]["c"], ts, f"tempo ({BK[name]['time_stop_bars']} velas)", p, ctx)
        # 4
        for name, b in st["books"].items():
            eq = b["cash"] + sum((q["reserve"] for q in b["pend"].values()), D(0)) + \
                 sum((p["qty"] * dec(st["last_close"].get(s, p["entry"])) for s, p in b["pos"].items()), D(0))
            b["equity"] = eq; b["peak"] = max(b["peak"], eq)
            dd = float(1 - eq / b["peak"]) if b["peak"] > 0 else 0.0
            b["max_dd"] = max(b["max_dd"], dd)
            if b["state"] != TRAINING: continue
            if eq >= CEIL:
                self._flatten(name, b, ts, "teto $1.000", ctx); b["state"], b["state_since"] = CEILING, ts
                self.on_event({"type": CEILING, "book": name, "ts": ts, "equity": str(b["equity"])})
            elif dd > float(DD_KILL):
                self._flatten(name, b, ts, "kill DD>20%", ctx); b["state"], b["state_since"] = HALTED, ts
                self.on_event({"type": HALTED, "book": name, "ts": ts, "equity": str(b["equity"]), "peak": str(b["peak"])})
        # 5
        close_ts = ts + M1
        shock = {}
        for sym, v in V.items():
            if "atr_bps" in v and abs(v["ret_bps"]) > FL["shock_ret_atr"] * max(v["atr_bps"], 1e-9):
                st["shock"][sym] = FL["shock_cooldown_bars"]
            elif st["shock"].get(sym): st["shock"][sym] -= 1
            shock[sym] = bool(st["shock"].get(sym))
        if ts < st["trade_from"]: st["last_ts"] = ts; return
        macro = None
        for name, b in st["books"].items():
            if b["state"] != TRAINING: continue
            S = BK[name]
            for sym in SYMS:
                v = V.get(sym)
                if not v or not v.get("ready"): continue
                if not (FL["atr_min_bps"] <= v["atr_bps"] <= FL["atr_max_bps"]): continue
                setup = self._entry(name, v)
                if not setup: continue
                b["n"]["signals"] += 1
                if shock[sym]: b["n"]["rej_shock"] += 1; continue
                if macro is None: macro = ctx.macro(close_ts) or "INSUFFICIENT_DATA"
                if macro == "RISK_OFF": b["n"]["rej_macro"] += 1; continue
                if sym in b["pos"] or sym in b["pend"] or len(b["pos"]) + len(b["pend"]) >= RK["max_open"]:
                    b["n"]["rej_busy"] += 1; continue
                active_from = close_ts
                if S["needs_book"]:
                    bk = None if ctx.catchup else ctx.book(sym, close_ts)
                    if not bk or abs(bk["ts"] - close_ts) > S["book_max_age_s"] * 1000: b["n"]["rej_no_book"] += 1; continue
                    if bk["spread_bps"] > S["max_spread_bps"] or bk["obi"] is None or bk["obi"] < S["obi_min"]:
                        b["n"]["rej_book_filter"] += 1; continue
                    active_from = max(close_ts, -(-bk["ts"] // M1) * M1)   # só depois da leitura do livro
                self._place(name, b, sym, setup, v, B[sym], ts, active_from, ctx)
        st["last_ts"] = ts

    def _flatten(self, name, b, ts, why, ctx):
        for sym in list(b["pend"]):
            b["cash"] += b["pend"][sym]["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
        for sym in list(b["pos"]):
            self._taker_exit(name, b, sym, dec(self.st["last_close"][sym]), ts, why, b["pos"][sym], ctx)
        b["equity"] = b["cash"]

    # ---------- sinais (congelados no SPEC) ----------
    @staticmethod
    def _entry(name, v):
        S = BK[name]; c = v["close"]
        if name in ("ems_vwap_mr", "ems_vwap_obi"):
            vw = v.get("vwap")
            if not vw: return None
            if c <= vw * (1 - S["vwap_dev_atr"] * v["atr_bps"] / 1e4) and v["rsi"] <= S["rsi_max"] and c > v["open"]:
                return "VWAP_MR"
        elif name == "ems_rsi_div":
            if v["low"] < v["div_low"] and v["rsi"] >= v["div_rsi"] + S["div_rsi_gap"] and v["rsi"] <= S["rsi_max"] and c > v["open"]:
                return "RSI_DIV"
        elif name == "ems_squeeze_bo":
            va = v["prev_vol_avg"]
            if v["squeeze_prev"] and c > v["bb_hi"] and v["vol"] > 0 and va is not None and v["vol"] > S["vol_mult"] * va:
                return "BB_SQUEEZE_BO"
        return None

    def _place(self, name, b, sym, setup, v, bar, ts, active_from, ctx):
        hs = ctx.hs(sym, ts); c = bar["c"]
        d = D(str(round(min(max(RK["stop_atr_mult"] * v["atr_bps"] / 1e4, RK["stop_min"]), RK["stop_max"]), 6)))
        tp_pct = d * D(str(RK["rr"]))
        cost_maker = TAKER + SLIP + 2 * hs; cost_taker = 2 * (TAKER + SLIP + hs)
        if tp_pct <= cost_maker: b["n"]["rej_cost"] += 1; return
        taker = BK[name].get("entry_mode") == "taker_if_edge" and tp_pct - cost_taker > MIN_EDGE   # maker primeiro
        entry = c * (1 + SLIP + hs) if taker else c * (1 - hs)
        stop, tp = entry * (1 - d), entry * (1 + tp_pct)
        r_per_qty = (entry - stop) + stop * self._exit_cost(hs) + (entry * TAKER if taker else D(0))
        qty = b["equity"] * RISK / r_per_qty
        cap = min(b["equity"] * CAP, b["cash"] / (TAKER_RESERVE_BUF if taker else 1))
        qty = min(qty, cap / entry)
        qty = (qty / STEP).to_integral_value(ROUND_DOWN) * STEP
        if qty * entry < MIN_NOT: b["n"]["rej_size"] += 1; return
        reserve = qty * entry * TAKER_RESERVE_BUF if taker else qty * entry
        b["cash"] -= reserve
        b["pend"][sym] = {"setup": setup, "kind": "taker" if taker else "maker", "limit": None if taker else entry, "qty": qty,
                          "reserve": reserve, "d": d, "stop": stop, "tp": tp, "signal_ts": ts, "active_from": active_from,
                          "expiry": ts + M1 + EX["entry_valid_bars"] * M1}
        b["n"]["placed"] += 1; b["n"]["taker" if taker else "maker"] += 1
