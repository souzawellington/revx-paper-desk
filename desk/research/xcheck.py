"""Cross-check do motor do sweep com vectorbt (Portfolio.from_signals) e Backtrader (Cerebro), venv opcional
/workspace/.venv-research. python -m desk.research.xcheck --sym BTC
Só simulação local; nenhuma corretora/credencial."""
from __future__ import annotations
import argparse, json
import numpy as np
from . import sweep as S


def ours(d, cfg, t0, t1):
    want = S.signal(d, cfg); tr, r = S.simulate(d, want, t0, t1)
    return want, tr, float(np.prod(1 + r[(d["start"] >= t0) & (d["start"] < t1)]) - 1)


def vbt_check(d, want, t0, t1):
    import pandas as pd, vectorbt as vbt
    m = (d["start"] >= t0) & (d["start"] < t1)
    idx = pd.to_datetime(d["start"][m], unit="ms")
    o, h, l, c = (pd.Series(d[k][m], index=idx) for k in ("open", "high", "low", "close"))
    w = pd.Series(np.r_[0, want[:-1]][m].astype(bool), index=idx)          # decidido em t-1, executa na abertura t
    ent, ex = w & ~w.shift(1, fill_value=False), ~w & w.shift(1, fill_value=False)
    pf = vbt.Portfolio.from_signals(c, ent, ex, price=o, open=o, high=h, low=l, fees=0.0009, slippage=0.001,
                                    sl_stop=0.08, init_cash=1.0, freq="1h")
    return {"ret": float(pf.total_return()), "trades": int(pf.trades.count())}


def bt_check(d, want, t0, t1):
    import backtrader as bt, pandas as pd
    m = (d["start"] >= t0) & (d["start"] < t1)
    df = pd.DataFrame({k: d[k][m] for k in ("open", "high", "low", "close", "volume")}, index=pd.to_datetime(d["start"][m], unit="ms"))
    df["want"] = want[m].astype(float)

    class Feed(bt.feeds.PandasData):
        lines = ("want",); params = (("want", -1),)

    class Strat(bt.Strategy):
        def __init__(self): self.n = 0; self.stop_o = None; self.blocked = False
        def next(self):
            if not self.position and self.data.want[0] == 1 and self.stop_o is None and not self.blocked:
                self.buy(size=self.broker.getvalue() * 0.98 / self.data.close[0]); self.n += 1
            elif self.position and self.data.want[0] == 0:
                self.close()
            if self.data.want[0] == 0: self.blocked = False
        def notify_order(self, o):
            if o.status != o.Completed: return
            if o.isbuy():
                self.stop_o = self.sell(size=o.executed.size, exectype=bt.Order.Stop, price=o.executed.price * 0.92)
            else:
                if self.stop_o is not None and o.ref == self.stop_o.ref: self.blocked = True
                elif self.stop_o is not None: self.cancel(self.stop_o)
                self.stop_o = None

    c = bt.Cerebro(stdstats=False); c.adddata(Feed(dataname=df)); c.addstrategy(Strat)
    c.broker.setcash(1.0); c.broker.setcommission(commission=0.0009); c.broker.set_slippage_perc(0.001)
    r = c.run()[0]
    return {"ret": c.broker.getvalue() - 1, "trades": r.n}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sym", default="BTC")
    ap.add_argument("--cfgs", default="sma_50_200_1h,donchian_100_50_1h,boll_20_2.0_4h,rsi_14_30_55_24h")
    ap.add_argument("--data", default="data_ext/coinbase"); a = ap.parse_args()
    d1 = S.load(a.data, a.sym); out = {}
    cmap = {c["id"]: c for c in S.configs()}
    for cid in a.cfgs.split(","):
        cfg = cmap[cid]; d = S.resample(d1, cfg["tf"])
        want, tr, ret = ours(d, cfg, S.DEV0, S.HOLD0)
        out[cid] = {"ours": {"ret": ret, "trades": len(tr)}}
        for name, fn in (("vectorbt", vbt_check), ("backtrader", bt_check)):
            try: out[cid][name] = fn(d, want, S.DEV0, S.HOLD0)
            except Exception as e: out[cid][name] = f"erro {type(e).__name__}: {e}"
    print(json.dumps(out, indent=1, default=float))
    json.dump(out, open("desk/state/research_xcheck.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
