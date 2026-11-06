"""Variantes de pesquisa (NÃO alteram o bot ao vivo).  python -m bot.variants
Usa o cache data/candles_*_60.json do backtest. Mesmo holdout cronológico 60/40 e mesmas regras base."""
from __future__ import annotations
import json, os
from dataclasses import dataclass, replace
from .config import Config
from .signals import technical_state
from .backtest import WARMUP


@dataclass(frozen=True)
class Variant:
    name: str
    interval_h: int = 1            # 1 = candles 60m; 4 = reamostrado
    exit_on_momentum_end: bool = False
    take_profit_r: float | None = None
    maker_entry: bool = False      # entrada limit/post-only: taxa 0% e sem slippage na entrada (otimista)
    maker_exit_tp: bool = False    # take-profit como limit em repouso: maker na saída de TP


VARIANTS = [
    Variant("base 1h (live)"),
    Variant("4h", 4),
    Variant("1h + saída fim momentum", exit_on_momentum_end=True),
    Variant("4h + saída fim momentum", 4, exit_on_momentum_end=True),
    Variant("1h + TP 2R", take_profit_r=2), Variant("1h + TP 3R", take_profit_r=3),
    Variant("4h + TP 2R", 4, take_profit_r=2), Variant("4h + TP 3R", 4, take_profit_r=3),
    Variant("1h maker (entrada+TP3R)", take_profit_r=3, maker_entry=True, maker_exit_tp=True),
    Variant("4h maker + fim momentum", 4, exit_on_momentum_end=True, maker_entry=True),
    Variant("4h maker + TP 3R", 4, take_profit_r=3, maker_entry=True, maker_exit_tp=True),
]


def resample(c: list[dict], hours: int) -> list[dict]:
    if hours == 1: return c
    ms = hours * 3_600_000; out = {}
    for x in c:
        k = x["start"] // ms * ms
        b = out.get(k)
        if b is None: out[k] = dict(x, start=k, n=1)
        else:
            b["high"] = max(b["high"], x["high"]); b["low"] = min(b["low"], x["low"])
            b["close"] = x["close"]; b["volume"] += x["volume"]; b["n"] += 1
    return [b for k, b in sorted(out.items()) if b["n"] == hours]  # só blocos completos


def simulate(c: list[dict], cfg: Config, v: Variant) -> list[dict]:
    o = [x["open"] for x in c]; h = [x["high"] for x in c]; l = [x["low"] for x in c]
    cl = [x["close"] for x in c]; vo = [x["volume"] for x in c]
    taker = cfg.taker_fee + cfg.slippage_est
    trades, i, n = [], WARMUP, len(c)
    st = lambda k: technical_state(h[:k + 1], l[:k + 1], cl[:k + 1], vo[:k + 1], cfg)
    while i < n - 1:
        active, *_, stop_atr = st(i)
        if not active: i += 1; continue
        j = i + 1; entry = o[j]
        if entry <= stop_atr: i += 1; continue
        risk = (entry - stop_atr) / entry
        tp = entry * (1 + v.take_profit_r * risk) if v.take_profit_r else None
        peak, exit_px, why = entry, None, ""
        while j < n:
            lvl = max(stop_atr, max(entry, peak) * (1 - cfg.position_hard_stop_pct))
            if j > i + 1 and o[j] <= lvl: exit_px, why = o[j], "STOP_GAP"; break
            if l[j] <= lvl: exit_px, why = min(lvl, o[j]) if j > i + 1 else lvl, "STOP"; break   # stop antes do TP (conservador)
            if tp and h[j] >= tp: exit_px, why = max(tp, o[j]) if j > i + 1 else tp, "TP"; break
            peak = max(peak, cl[j])
            if v.exit_on_momentum_end and j < n - 1 and not st(j)[0]:
                j += 1; exit_px, why = o[j], "MOMENTUM_END"; break   # sinal no fecho de j, sai na abertura j+1
            j += 1
        if exit_px is None: break
        ce = 0.0 if v.maker_entry else taker
        cx = cfg.maker_fee if (why == "TP" and v.maker_exit_tp) else taker
        r_net = ((exit_px * (1 - cx)) / (entry * (1 + ce)) - 1) / risk
        trades.append({"entry_ts": c[i + 1]["start"], "exit_ts": c[j]["start"], "r_net": r_net, "why": why})
        i = j
    return trades


def summarize(tr):
    n = len(tr); w = [t["r_net"] for t in tr if t["r_net"] > 0]
    return {"n": n, "p": len(w) / n if n else 0.0, "ev_net_r": sum(t["r_net"] for t in tr) / n if n else 0.0}


def run(cfg: Config, symbols=None, data_dir="data"):
    res = []
    for sym in symbols or cfg.symbols:
        raw = json.load(open(os.path.join(data_dir, f"candles_{sym}_60.json")))
        for v in VARIANTS:
            c = resample(raw, v.interval_h)
            tr = simulate(c, cfg, v)
            split = c[int(len(c) * (1 - cfg.holdout_fraction))]["start"]
            res.append({"symbol": sym, "variant": v.name, "full": summarize(tr),
                        "is": summarize([t for t in tr if t["exit_ts"] < split]),
                        "oos": summarize([t for t in tr if t["entry_ts"] >= split])})
    return res


def main():
    cfg = Config(); res = run(cfg)
    json.dump(res, open("data/variants_results.json", "w"), indent=2)
    print(f"{'símbolo':8} {'variante':28} {'n':>4} {'p':>5} {'EVnet':>7} | {'nIS':>4} {'EVis':>7} | {'nOOS':>4} {'pOOS':>5} {'EVoos':>7}")
    for r in res:
        f, i, o = r["full"], r["is"], r["oos"]
        print(f"{r['symbol']:8} {r['variant']:28} {f['n']:4} {f['p']:5.2f} {f['ev_net_r']:+7.3f} | {i['n']:4} {i['ev_net_r']:+7.3f} | {o['n']:4} {o['p']:5.2f} {o['ev_net_r']:+7.3f}")


if __name__ == "__main__":
    main()
