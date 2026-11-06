"""Motor determinístico dos livros NEWS (paper). Sem rede, sem broker, sem chaves.
evaluate(): decide uma entrada a partir de features já calculadas (notícia + mercado) → ordem pendente;
bar(): processa uma vela 1m FECHADA de um símbolo (enchimentos, stop/alvo, tempo); mark(): marcação, pico/DD, kill, teto.
Dinheiro em Decimal; features em float (só decidem)."""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from .spec import SPEC

M1 = 60_000
D = Decimal
EX, RK, BK = SPEC["execution"], SPEC["risk"], SPEC["books"]
BOOKS = list(BK)
BROKER = None                     # deliberado: nunca há broker aqui
TRAINING, HALTED, CEILING = "PAPER_TRAINING", "HALTED_MAX_DRAWDOWN", "CEILING_PAUSED"
TAKER, MAKER, SLIP = D(EX["taker_fee"]), D(EX["maker_fee"]), D(EX["slippage"])
START, RISK, CAP, STEP, MIN_NOT = D(RK["start_equity"]), D(RK["risk_pct"]), D(RK["pos_cap_frac"]), D(RK["qty_step"]), D(RK["min_notional"])
DD_KILL, CEIL = D(RK["dd_kill"]), D(RK["ceiling"])
RESERVE_BUF = D("1.02")
FALLBACK_HS = D("0.0020")
MONEY = {"cash", "equity", "peak", "qty", "limit", "entry", "stop", "tp", "reserve", "d", "r_unit", "entry_fee"}


def dec(x) -> Decimal: return x if isinstance(x, Decimal) else D(str(x))


def _conv(o, f):
    if isinstance(o, dict): return {k: (f(v) if k in MONEY and v is not None and not isinstance(v, (dict, list)) else _conv(v, f)) for k, v in o.items()}
    if isinstance(o, list): return [_conv(v, f) for v in o]
    return o


def to_json(st): return _conv(st, str)


def from_json(st): return _conv(st, dec)


def new_book(eq=START):
    eq = dec(eq)
    return {"cash": eq, "equity": eq, "peak": eq, "max_dd": 0.0, "state": TRAINING, "state_since": None, "pos": {}, "pend": {},
            "cycles": 0, "cooldown": {},
            "n": {"evaluated": 0, "placed": 0, "filled": 0, "unfilled": 0, "rej_filters": 0, "rej_cost": 0, "rej_macro": 0,
                  "rej_busy": 0, "rej_cooldown": 0, "rej_size": 0}}


def new_state(trade_from=0):
    return {"spec_id": SPEC["id"], "trade_from": trade_from, "last_bar": {}, "last_close": {}, "books": {b: new_book() for b in BOOKS}}


def stop_dist(atr_pct):
    return D(str(round(min(max(RK["stop_atr_mult"] * atr_pct, RK["stop_min"]), RK["stop_max"]), 6)))


def filters(name, f):
    """Motivo de rejeição (str) ou None. f: news_score, vol_ratio, mom_15m, runup, chg_24h (floats)."""
    S = BK[name]
    if f["news_score"] < SPEC["nlp"]["positive_min"]: return "sem notícia positiva"
    if f["vol_ratio"] is None or f["vol_ratio"] < S["min_vol_ratio"]: return f"volume fraco ({f['vol_ratio'] and round(f['vol_ratio'], 2)}× < {S['min_vol_ratio']}×)"
    if f["mom_15m"] is None or f["mom_15m"] < S["mom_min"]: return f"sem momentum (15m {f['mom_15m'] and round(100 * f['mom_15m'], 2)}%)"
    if S["mom_max"] is not None and f["mom_15m"] > S["mom_max"]: return f"já subiu demais em 15m ({100 * f['mom_15m']:.2f}%)"
    if f["runup"] is not None and f["runup"] > S["max_runup"]: return f"anti-topo: subiu {100 * f['runup']:.2f}% desde a notícia"
    if f["chg_24h"] is not None and f["chg_24h"] > S["max_chg_24h"]: return f"anti-topo: +{100 * f['chg_24h']:.1f}% em 24 h"
    return None


class Engine:
    def __init__(self, state, on_trade=None, on_event=None):
        self.st = state; self.on_trade = on_trade or (lambda t: None); self.on_event = on_event or (lambda e: None)

    # ---------- decisão ----------
    def evaluate(self, name, sym, f, now, hs, macro=None):
        """Avalia uma moeda para um livro. Devolve (aceite: bool, motivo: str). Nunca força trades."""
        b = self.st["books"][name]; S = BK[name]; b["n"]["evaluated"] += 1
        if b["state"] != TRAINING: return False, f"livro {b['state']}"
        if now < self.st["trade_from"]: return False, "antes do início"
        why = filters(name, f)
        if why: b["n"]["rej_filters"] += 1; return False, why
        if macro == "RISK_OFF": b["n"]["rej_macro"] += 1; return False, "macro RISK_OFF"
        if b["cooldown"].get(sym, 0) > now: b["n"]["rej_cooldown"] += 1; return False, "cooldown 6 h nesta moeda"
        if sym in b["pos"] or sym in b["pend"] or len(b["pos"]) + len(b["pend"]) >= RK["max_open"]:
            b["n"]["rej_busy"] += 1; return False, "ocupado (mesma moeda ou 3 abertas)"
        hs = dec(hs if hs is not None else FALLBACK_HS); c = dec(f["close"])
        d = stop_dist(f["atr_pct"]); tp_pct = d * D(str(RK["rr"]))
        taker = S["entry_mode"] == "taker"
        cost = 2 * (TAKER + SLIP + hs) if taker else TAKER + SLIP + 2 * hs
        if tp_pct - cost < D(str(S["min_edge"])): b["n"]["rej_cost"] += 1; return False, f"alvo {100 * float(tp_pct):.2f}% não paga custos {100 * float(cost):.2f}% + margem"
        entry = c * (1 + SLIP + hs) if taker else c * (1 - d * D(str(S["pullback_frac_of_stop"])))
        stop = entry * (1 - d)
        r_per_qty = (entry - stop) + stop * (TAKER + SLIP + hs) + (entry * TAKER if taker else D(0))
        qty = b["equity"] * RISK / r_per_qty
        cap = min(b["equity"] * CAP, b["cash"] / (RESERVE_BUF if taker else 1))
        qty = min(qty, cap / entry)
        qty = (qty / STEP).to_integral_value(ROUND_DOWN) * STEP
        if qty * entry < MIN_NOT: b["n"]["rej_size"] += 1; return False, "tamanho abaixo do mínimo"
        reserve = qty * entry * RESERVE_BUF if taker else qty * entry
        b["cash"] -= reserve
        active = (now // M1 + 1) * M1
        valid = S.get("valid_min", 3) * M1
        b["pend"][sym] = {"kind": "taker" if taker else "maker", "limit": None if taker else entry, "qty": qty, "reserve": reserve,
                          "d": d, "stop": stop, "tp": entry * (1 + tp_pct), "signal_ts": now, "active_from": active,
                          "expiry": active + valid, "news": f.get("news_ids", [])[:5], "news_score": f["news_score"]}
        b["cooldown"][sym] = now + RK["cooldown_h"] * 3_600_000
        b["n"]["placed"] += 1
        return True, ("compra a mercado no próximo minuto" if taker else f"limite maker {float(entry):.6g} por 30 min")

    # ---------- execução ----------
    def _close(self, name, b, sym, p, px, fee, slip, ts, why, hs):
        pnl = p["qty"] * (px - p["entry"]) - fee - p["entry_fee"]
        b["cash"] += p["qty"] * px - fee
        del b["pos"][sym]
        r = pnl / p["r_unit"] if p["r_unit"] > 0 else D(0)
        self.on_trade({"book": name, "symbol": sym, "entry_kind": p["kind"], "signal_ts": p["signal_ts"], "fill_ts": p["fill_ts"],
                       "exit_ts": ts, "entry": p["entry"], "stop": p["stop"], "tp": p["tp"], "stop_pct": p["d"], "qty": p["qty"],
                       "notional": p["qty"] * p["entry"], "exit": px, "reason": why, "fee": fee + p["entry_fee"], "slip_cost": slip,
                       "pnl": pnl, "r_unit": p["r_unit"], "r": r, "news_score": p.get("news_score"), "news": "|".join(p.get("news") or [])})

    def _taker_exit(self, name, b, sym, ref, ts, why, p, hs):
        px = ref * (1 - SLIP - hs); fee = p["qty"] * px * TAKER; slip = p["qty"] * ref * (SLIP + hs)
        self._close(name, b, sym, p, px, fee, slip, ts, why, hs)

    def _fill(self, b, sym, q, px, fee, ts, hs):
        cost = q["qty"] * px + fee
        if cost > q["reserve"]:
            q["qty"] = ((q["reserve"] / (px * (1 + (TAKER if q["kind"] == "taker" else MAKER)))) / STEP).to_integral_value(ROUND_DOWN) * STEP
            fee = q["qty"] * px * (TAKER if q["kind"] == "taker" else MAKER); cost = q["qty"] * px + fee
        b["cash"] += q["reserve"] - cost; del b["pend"][sym]; b["n"]["filled"] += 1
        d = q["d"]
        stop, tp = (px * (1 - d), px * (1 + d * D(str(RK["rr"])))) if q["kind"] == "taker" else (q["stop"], q["tp"])
        p = {"kind": q["kind"], "signal_ts": q["signal_ts"], "fill_ts": ts, "entry": px, "qty": q["qty"], "stop": stop, "tp": tp, "d": d,
             "entry_fee": fee, "news": q.get("news"), "news_score": q.get("news_score"),
             "r_unit": q["qty"] * (px - stop) + q["qty"] * stop * (TAKER + SLIP + hs) + fee}
        b["pos"][sym] = p
        return p

    def bar(self, sym, ts, o, h, l, c, hs=None):
        """Uma vela 1m FECHADA (início ts) de `sym`, processada em ordem cronológica e só uma vez."""
        if self.st["last_bar"].get(sym) is not None and ts <= self.st["last_bar"][sym]: return
        hs = dec(hs if hs is not None else FALLBACK_HS); o, h, l, c = dec(o), dec(h), dec(l), dec(c)
        for name, b in self.st["books"].items():
            q = b["pend"].get(sym)
            if q:
                if ts >= q["expiry"]:
                    b["cash"] += q["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
                elif ts >= q["active_from"]:
                    p = None
                    if q["kind"] == "taker":
                        px = o * (1 + SLIP + hs); p = self._fill(b, sym, q, px, q["qty"] * px * TAKER, ts, hs)
                    elif l < q["limit"]:
                        p = self._fill(b, sym, q, q["limit"], q["qty"] * q["limit"] * MAKER, ts, hs)
                    if p and l <= p["stop"]:
                        self._taker_exit(name, b, sym, p["stop"], ts, "stop (mesma vela da entrada)", p, hs)
                    if p: continue
            p = b["pos"].get(sym)
            if p and p["fill_ts"] < ts:
                if l <= p["stop"]: self._taker_exit(name, b, sym, min(p["stop"], o), ts, "stop", p, hs); continue
                if h > p["tp"]: self._close(name, b, sym, p, p["tp"], p["qty"] * p["tp"] * MAKER, D(0), ts, "alvo (maker)", hs); continue
                if ts + M1 - p["fill_ts"] >= BK[name]["time_stop_min"] * M1:
                    self._taker_exit(name, b, sym, c, ts, f"tempo ({BK[name]['time_stop_min']} min)", p, hs)
        self.st["last_bar"][sym] = ts; self.st["last_close"][sym] = str(c)

    def mark(self, ts, prices=None):
        prices = prices or {}
        for name, b in self.st["books"].items():
            eq = b["cash"] + sum((q["reserve"] for q in b["pend"].values()), D(0)) + \
                 sum((p["qty"] * dec(prices.get(s) or self.st["last_close"].get(s) or p["entry"]) for s, p in b["pos"].items()), D(0))
            b["equity"] = eq; b["peak"] = max(b["peak"], eq)
            dd = float(1 - eq / b["peak"]) if b["peak"] > 0 else 0.0
            b["max_dd"] = max(b["max_dd"], dd)
            if b["state"] != TRAINING: continue
            if eq >= CEIL:
                self._flatten(name, b, ts, "teto $1.000", prices); b["state"], b["state_since"] = CEILING, ts
                self.on_event({"type": CEILING, "book": name, "ts": ts, "equity": str(b["equity"])})
            elif dd > float(DD_KILL):
                self._flatten(name, b, ts, "kill DD>20%", prices); b["state"], b["state_since"] = HALTED, ts
                self.on_event({"type": HALTED, "book": name, "ts": ts, "equity": str(b["equity"]), "peak": str(b["peak"])})

    def _flatten(self, name, b, ts, why, prices):
        for sym in list(b["pend"]):
            b["cash"] += b["pend"][sym]["reserve"]; del b["pend"][sym]; b["n"]["unfilled"] += 1
        for sym in list(b["pos"]):
            ref = dec(prices.get(sym) or self.st["last_close"].get(sym) or b["pos"][sym]["entry"])
            self._taker_exit(name, b, sym, ref, ts, why, b["pos"][sym], FALLBACK_HS)
        b["equity"] = b["cash"]
