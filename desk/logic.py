"""Lógica PURA do desk (partilhada por papéis ao vivo e pelo replay). Sem I/O, sem look-ahead:
cada função recebe apenas velas JÁ FECHADAS até ao instante de decisão."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

H = 3_600_000
D = 24 * H


def is_doji(c, frac):
    rng = c["high"] - c["low"]
    return rng > 0 and abs(c["close"] - c["open"]) <= frac * rng


def up_flip_at(d: list[dict], k: int, rules) -> bool:
    """Velas 1D d[k-2]=C1, d[k-1]=C2, d[k]=C3."""
    if k < 2: return False
    c1, c2, c3 = d[k - 2], d[k - 1], d[k]
    c1_ok = c1["close"] > c1["open"] or is_doji(c1, rules.doji_body_frac)
    return (c1_ok and c2["close"] > c1["close"] and c3["close"] > c2["close"]
            and c2["low"] > c1["low"] and c3["low"] > c1["low"])


def down_flip_at(d, k, rules) -> bool:
    if k < 2: return False
    c1, c2, c3 = d[k - 2], d[k - 1], d[k]
    c1_ok = c1["close"] < c1["open"] or is_doji(c1, rules.doji_body_frac)
    return (c1_ok and c2["close"] < c1["close"] and c3["close"] < c2["close"]
            and c2["high"] < c1["high"] and c3["high"] < c1["high"])


@dataclass
class Flip:
    anchor_low: float
    c1_start: int
    flip_date: int     # start da vela C3 (ms)
    flip_close_ts: int  # fecho de C3


def active_up_flip(d: list[dict], rules) -> Optional[Flip]:
    """Flip de alta mais recente dentro de flip_lookback_days ainda válido (nenhum fecho 1D < âncora depois de C3)."""
    n = len(d)
    for k in range(n - 1, max(1, n - 1 - rules.flip_lookback_days), -1):
        if up_flip_at(d, k, rules):
            anchor = d[k - 2]["low"]
            if all(x["close"] >= anchor for x in d[k + 1:]):
                return Flip(anchor, d[k - 2]["start"], d[k]["start"], d[k]["start"] + D)
            return None  # o flip mais recente foi invalidado
    return None


def recent_down_flip(d, rules) -> Optional[int]:
    n = len(d)
    for k in range(n - 1, max(1, n - 1 - rules.flip_lookback_days), -1):
        if down_flip_at(d, k, rules): return d[k]["start"]
    return None


def h4_pullback(h4: list[dict]) -> bool:
    if len(h4) < 2: return False
    a, b = h4[-2], h4[-1]
    return b["close"] < b["open"] and b["close"] < a["close"]


@dataclass
class Zone:
    zid: str
    top: float
    bottom: float
    formed_ts: int        # start da vela i+1 (zona existe após o fecho desta)
    status: str = "UNTESTED"   # UNTESTED|TESTED|INVALID|CONFIRMED|USED
    tested_ts: Optional[int] = None
    test_low: Optional[float] = None
    confirmed: bool = False
    entry: Optional[float] = None
    stop: Optional[float] = None
    confirm_ts: Optional[int] = None
    last_h1: int = -1
    last_h4: int = -1


def find_fvgs(h4: list[dict], symbol: str, flip: Flip) -> list[Zone]:
    """FVGs de alta em velas 4H desde a vela C1 (âncora) até agora, dentro de [âncora, máxima atual]."""
    seg = [c for c in h4 if c["start"] >= flip.c1_start]
    if len(seg) < 3: return []
    hi = max(c["high"] for c in seg)
    zs = []
    for i in range(1, len(seg) - 1):
        a, c = seg[i - 1], seg[i + 1]
        if c["low"] > a["high"]:
            top, bot = c["low"], a["high"]
            if bot >= flip.anchor_low and top <= hi:
                zs.append(Zone(f"{symbol}:{seg[i]['start']}", top, bot, c["start"]))
    return sorted(zs, key=lambda z: -z.top)   # escada de cima para baixo


def update_zone(z: Zone, h4: list[dict], h1: list[dict], rules) -> Zone:
    """Incremental e cronológico: processa só velas fechadas ainda não vistas (posteriores a formed_ts+4H).
    Evento 4H: fecho < bottom -> INVALID. Evento 1H: teste (low <= top), invalidade (close < bottom) e confirmação."""
    if z.status in ("INVALID", "USED", "CONFIRMED"): return z
    ready = z.formed_ts + 4 * H
    ev = [(c["start"] + 4 * H, 0, c) for c in h4 if c["start"] >= ready and c["start"] > z.last_h4]
    ev += [(c["start"] + H, 1, c) for c in h1 if c["start"] >= ready and c["start"] > z.last_h1]
    for _, kind, c in sorted(ev, key=lambda e: (e[0], e[1])):
        if kind == 0:
            z.last_h4 = c["start"]
            if c["close"] < z.bottom: z.status = "INVALID"; return z
            continue
        z.last_h1 = c["start"]
        if z.status == "UNTESTED":
            if c["low"] > z.top: continue
            z.status, z.tested_ts, z.test_low = "TESTED", c["start"], c["low"]
        else:
            z.test_low = min(z.test_low, c["low"])
        if c["close"] < z.bottom: z.status = "INVALID"; return z
        if c["close"] > c["open"] and c["close"] > z.top:
            return _confirm(z, c, rules)
    return z


def _confirm(z: Zone, c, rules) -> Zone:
    z.status, z.confirmed, z.entry, z.confirm_ts = "CONFIRMED", True, c["close"], c["start"] + H
    z.stop = max(z.test_low, z.entry * (1 - rules.hard_stop_pct))
    if z.stop >= z.entry: z.status, z.confirmed = "INVALID", False
    return z


def size_trade(equity, entry, stop, risk_frac, rules, kelly_frac=None):
    """Unidades = min(risco, quarter-Kelly ledger, teto 15%) em notional."""
    per_unit = entry - stop
    if per_unit <= 0: return 0.0, {"why": "stop>=entry"}
    risk_units = equity * risk_frac / per_unit
    caps = {"risk": risk_units * entry, "cap15": rules.max_position_frac * equity}
    if kelly_frac is not None: caps["quarter_kelly"] = max(0.0, kelly_frac) * equity
    notional = min(caps.values())
    return notional / entry, {"binding": min(caps, key=caps.get), **{k: round(v, 2) for k, v in caps.items()}}


def tp_price(entry: float, stop: float, take_profit_r: float) -> float:
    """Pré-comprometido: entrada + take_profit_r × (entrada − stop). Immutable após TAKEN."""
    r = entry - stop
    if r <= 0: raise ValueError("stop >= entry")
    return entry + take_profit_r * r


@dataclass
class Position:
    pid: str
    symbol: str
    entry: float
    stop: float
    qty: float
    risk_frac: float
    add_number: int
    anchor_low: float
    opened_ts: int
    peak: float = 0.0
    at_be: bool = False
    initial_stop: float = 0.0
    tp_price: Optional[float] = None   # frozen at plan/entry; never mutated after TAKEN
    initial_tp: Optional[float] = None
    stale_flagged: bool = False


def check_exit(pos: Position, c: dict, rules) -> Optional[tuple[str, float]]:
    """Avalia UMA vela 1H fechada (intrabar: stop / hard-stop / take-profit).
    Se stop e TP no mesmo candle → STOP (conservador). Nunca mutar tp_price aqui."""
    hard = max(pos.entry, pos.peak) * (1 - rules.hard_stop_pct)
    lvl = max(pos.stop, hard)
    tp = pos.tp_price
    # gap through stop first
    if c["open"] <= lvl:
        return ("HARD_STOP_8PCT" if hard >= pos.stop else "STOP") + "_GAP", c["open"]
    # gap through TP (abertura já acima do TP)
    if tp is not None and c["open"] >= tp:
        return "TAKE_PROFIT_GAP", c["open"]
    hit_stop = c["low"] <= lvl
    hit_tp = tp is not None and c["high"] >= tp
    if hit_stop and hit_tp:
        return ("HARD_STOP_8PCT" if hard >= pos.stop else "STOP"), lvl  # conservador
    if hit_stop:
        return ("HARD_STOP_8PCT" if hard >= pos.stop else "STOP"), lvl
    if hit_tp:
        return "TAKE_PROFIT", tp
    return None


def after_bar(pos: Position, c: dict, rules):
    """Atualiza pico e breakeven DEPOIS de avaliar a saída na vela."""
    pos.peak = max(pos.peak, c["close"])
    r = pos.entry - pos.initial_stop
    if not pos.at_be and c["high"] >= pos.entry + rules.be_trigger_r * r:
        pos.at_be = True
        if rules.p.get("be_move_stop", True):
            pos.stop = max(pos.stop, pos.entry)


def daily_anchor_exit(pos: Position, d_close: float) -> bool:
    return d_close < pos.anchor_low


def is_stale(pos: Position, now_ms: int, last_close: float, rules) -> bool:
    return now_ms - pos.opened_ts >= rules.stale_hours * H and abs(last_close / pos.entry - 1) < rules.stale_band


def trade_r(entry, exit_px, initial_stop, rules):
    """R líquido: (PnL − custos) / risco inicial em preço. Devolve dicionário com linhas separadas."""
    risk = entry - initial_stop
    slip_in = entry * rules.slippage; slip_out = exit_px * rules.slippage
    fill_in, fill_out = entry + slip_in, exit_px - slip_out
    fee = (fill_in + fill_out) * rules.taker_fee
    gross = exit_px - entry
    net = fill_out - fill_in - fee
    return {"gross_r": gross / risk, "net_r": net / risk, "fee_per_unit": fee,
            "slippage_per_unit": slip_in + slip_out, "fill_in": fill_in, "fill_out": fill_out}


def expected_ev_r(take_profit_r: float, rules, win_p: float | None = None) -> float:
    """EV em R após fees+slippage, assumindo win→+TP_R, loss→−1R.
    win_p default = 1/(1+take_profit_r) (break-even teórico sem custos); custo round-trip em R ≈ 2*(fee+slip)/risk_frac_price.
    Aqui usamos custo por unidade de risco: cost_r = 2*(taker_fee+slippage) / ((entry-stop)/entry) — mas sem preço,
    aproximamos cost_r = 2*(taker+slip) / 0.01 (risco típico 1% de preço) OU passamos risk_frac.
    Preferir expected_ev_r_for_plan.
    """
    p = win_p if win_p is not None else float(rules.threshold_win_rate)
    risk_price_frac = 0.01
    cost_r = 2.0 * (rules.taker_fee + rules.slippage) / risk_price_frac
    return p * take_profit_r - (1 - p) * 1.0 - cost_r


def expected_ev_r_for_plan(entry: float, stop: float, take_profit_r: float, rules, win_p: float | None = None) -> float:
    """EV em múltiplos de R após custos round-trip, dado stop distance real.
    win_p default = threshold_win_rate congelado (não o p de break-even sem custos, que com fees seria sempre ≤0)."""
    risk = entry - stop
    if risk <= 0: return -1e9
    risk_frac = risk / entry
    p = win_p if win_p is not None else float(rules.threshold_win_rate)
    cost_r = 2.0 * (rules.taker_fee + rules.slippage) / risk_frac
    return p * take_profit_r - (1.0 - p) * 1.0 - cost_r
