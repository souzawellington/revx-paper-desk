"""Verificação de alta fidelidade com NautilusTrader (LGPL-3.0) — OPCIONAL, corre num venv à parte:
  /workspace/.venv-nautilus/bin/python -m tools.nautilus_harness --intents /tmp/int_01.json --variant parity|maker_tp
Usa só o BacktestEngine (simulação local). NENHUM adapter live, nenhuma credencial, nenhuma rede.
Não importa nada de bot/ nem dos papéis do desk; lê velas JSON e intenções exportadas por desk/intents.py.
Fica FORA de desk/ (test_desk_never_writes_to_exchange proíbe chamadas de ordens em desk/); aqui as ordens são SIMULADAS no BacktestEngine local.

Mecânica:
- Conta CASH spot (sem margem/alavancagem), venue simulada "REVX", OMS NETTING, uma posição por par de cada vez
  (intenções sobrepostas no mesmo par são saltadas e contadas).
- Entrada: ordem MARKET na barra 1H cujo fecho = início da barra de fill da referência (fecho ≈ abertura seguinte).
- Stop: STOP_MARKET (taker). Atualizado após cada barra: max(stop inicial, entrada se BE, máx(entrada,pico)×(1−8%)) — igual ao desk.
- TP: variante `parity` = MARKET_IF_TOUCHED (taker, como o nosso replay); `maker_tp` = LIMIT (0% maker na Revolut X).
- Saída forçada (âncora 1D / sinal) = MARKET no fecho da barra indicada.
- bar_adaptive_high_low_ordering=True (ordem H/L mais provável); reject_stop_orders=False.
- Fees via MakerTakerFeeModel (maker 0%, taker 0.09%). Slippage percentual do desk (0.1%/lado) aplicada a posteriori em `net_r_slip`.
"""
from __future__ import annotations
import argparse, json, math, os
from decimal import Decimal

H = 3_600_000
NS = 1_000_000


def _prec(px):
    return int(min(8, max(2, 6 - math.floor(math.log10(px)))))


def run_symbol(symbol, bars_rows, intents, variant="parity", taker=0.0009, maker=0.0, notional=1500.0):
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.backtest.models import FillModel, MakerTakerFeeModel
    from nautilus_trader.config import LoggingConfig, StrategyConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.objects import Currency
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TriggerType, CurrencyType, TimeInForce
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.trading.strategy import Strategy

    base = symbol.split("-")[0]
    pp = _prec(sorted(r["close"] for r in bars_rows)[len(bars_rows) // 2]); sp = 6
    venue = Venue("REVX"); iid = InstrumentId(Symbol(f"{base}/USD"), venue)
    try: bcur = Currency.from_str(base)
    except Exception: bcur = None
    if bcur is None or bcur.currency_type != CurrencyType.CRYPTO:
        bcur = Currency(base, 8, 0, base, CurrencyType.CRYPTO)
    inst = CurrencyPair(iid, Symbol(f"{base}/USD"), bcur, USD, pp, sp, Price(10 ** -pp, pp), Quantity(10 ** -sp, sp), 0, 0,
                        maker_fee=Decimal(str(maker)), taker_fee=Decimal(str(taker)))
    bt = BarType.from_str(f"{base}/USD.REVX-1-HOUR-LAST-EXTERNAL")
    bars = []
    for r in bars_rows:
        o, h, l, c = (round(r[k], pp) for k in ("open", "high", "low", "close"))
        h = max(h, o, c); l = min(l, o, c)
        ts = (r["start"] + H) * NS
        bars.append(Bar(bt, Price(o, pp), Price(h, pp), Price(l, pp), Price(c, pp), Quantity(max(r.get("volume", 0), 0), sp), ts, ts))

    eng = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR"), trader_id="DESK-001"))
    eng.add_venue(venue, OmsType.NETTING, AccountType.CASH, [Money(10_000_000, USD)], base_currency=None,
                  fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7), fee_model=MakerTakerFeeModel(),
                  bar_adaptive_high_low_ordering=True, reject_stop_orders=False)
    eng.add_instrument(inst); eng.add_data(bars)

    by_entry = {}
    skipped = 0; last_end = -1
    for it in sorted(intents, key=lambda x: x["entry_ts"]):
        if it["entry_ts"] <= last_end: skipped += 1; continue
        by_entry[it["entry_ts"]] = it
        last_end = it.get("forced_exit_ts") or it.get("_ref_exit_ts") or it["entry_ts"]
    trades = []; voids = []

    class Harness(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id="HARNESS-001")); self.st = None

        def on_start(self): self.subscribe_bars(bt)

        def on_bar(self, bar):
            start = bar.ts_event // NS - H; close_t = bar.ts_event // NS
            s = self.st
            if s and s.get("entry_px") is not None and s.get("open"):
                c, hi = float(bar.close), float(bar.high)
                s["peak"] = max(s["peak"], c)
                r = s["entry_px"] - s["init_stop"]
                if s["be"] is not None and not s["at_be"] and hi >= s["entry_px"] + s["be"] * r:
                    s["at_be"] = True; s["stop"] = max(s["stop"], s["entry_px"])
                lvl = s["stop"]
                if s["trail"]: lvl = max(lvl, max(s["entry_px"], s["peak"]) * (1 - s["trail"]))
                if s["stop_order"] is not None and lvl > s["cur_trig"] + 10 ** -pp and s["stop_order"].is_open:
                    self.modify_order(s["stop_order"], trigger_price=Price(lvl, pp)); s["cur_trig"] = lvl
                if s["it"].get("forced_exit_ts") is not None and start == s["it"]["forced_exit_ts"]:
                    self._flat("FORCED")
            # nova entrada: o fill de referência é a abertura de start+H == este fecho
            if (self.st is None) and close_t in by_entry:
                it = by_entry[close_t]; q = round(notional / float(bar.close), sp)
                o = self.order_factory.market(iid, OrderSide.BUY, Quantity(q, sp))
                self.st = {"it": it, "qty": q, "entry_px": None, "open": False, "stop_order": None, "tp_order": None,
                           "fees": 0.0, "peak": 0.0, "at_be": False, "be": it.get("be_trigger_r"), "trail": it.get("trail_hard_pct")}
                self.submit_order(o)

        def _flat(self, why):
            s = self.st
            for k in ("stop_order", "tp_order"):
                if s[k] is not None and s[k].is_open: self.cancel_order(s[k])
            s["pending_why"] = why
            self.submit_order(self.order_factory.market(iid, OrderSide.SELL, Quantity(s["qty"], sp)))

        def on_order_filled(self, ev):
            s = self.st
            if s is None: return
            px = float(ev.last_px); q = float(ev.last_qty)
            fee = float(ev.commission.as_double()) * (1.0 if ev.commission.currency == USD else px)
            s["fees"] += fee
            eps = 10 ** -sp / 2
            if ev.order_side == OrderSide.BUY:
                s["bq"] = s.get("bq", 0.0) + q; s["bv"] = s.get("bv", 0.0) + q * px
                s["partial_fills"] = s.get("partial_fills", 0) + 1
                if s["bq"] < s["qty"] - eps: return            # espera fill completo (fills parciais por volume da barra)
                px = s["bv"] / s["bq"]
                it = s["it"]; s["entry_px"] = px; s["open"] = True; s["peak"] = px
                s["init_stop"] = it["stop_abs"] if it.get("stop_abs") else px * (1 - it["stop_pct"])
                if px <= s["init_stop"]:   # como o ENTRY_VOID do replay: fill no/abaixo do stop
                    s["void"] = True; self._flat("VOID"); return
                s["stop"] = s["init_stop"]; tp = it["tp_abs"] if it.get("tp_abs") else (px * (1 + it["tp_pct"]) if it.get("tp_pct") else None)
                lvl = s["stop"]
                if s["trail"]: lvl = max(lvl, px * (1 - s["trail"]))
                s["cur_trig"] = lvl
                so = self.order_factory.stop_market(iid, OrderSide.SELL, Quantity(s["qty"], sp), Price(lvl, pp),
                                                    trigger_type=TriggerType.LAST_PRICE, reduce_only=True)
                s["stop_order"] = so; self.submit_order(so)
                if tp is not None:
                    if variant == "maker_tp":
                        to = self.order_factory.limit(iid, OrderSide.SELL, Quantity(s["qty"], sp), Price(tp, pp), post_only=True, reduce_only=True)
                    else:
                        to = self.order_factory.market_if_touched(iid, OrderSide.SELL, Quantity(s["qty"], sp), Price(tp, pp),
                                                                  trigger_type=TriggerType.LAST_PRICE, reduce_only=True)
                    s["tp_order"] = to; self.submit_order(to)
            else:
                s["sq"] = s.get("sq", 0.0) + q; s["sv"] = s.get("sv", 0.0) + q * px
                if s["sq"] < s["qty"] - eps: return
                px = s["sv"] / s["sq"]; q = s["sq"]
                why = s.get("pending_why") or ("TP" if s["tp_order"] is not None and ev.client_order_id == s["tp_order"].client_order_id else "STOP")
                for k in ("stop_order", "tp_order"):
                    o = s[k]
                    if o is not None and o.client_order_id != ev.client_order_id and o.is_open: self.cancel_order(o)
                if s.get("void"):
                    voids.append(s["it"]["entry_ts"]); self.st = None; return
                e = s["entry_px"]; risk = e - s["init_stop"]
                net = (px - e) * q - s["fees"]
                slip = 0.001 * (e + px) * q
                trades.append({"symbol": symbol, "entry_ts": s["it"]["entry_ts"], "exit_ts": ev.ts_event // NS - H, "entry": e, "exit": px,
                               "why": why, "net_r": net / (risk * q) if risk > 0 else 0.0,
                               "net_r_slip": (net - slip) / (risk * q) if risk > 0 else 0.0,
                               "fees": s["fees"], "fills": s.get("partial_fills", 1), "ref_net_r": s["it"].get("ref_net_r"), "ref_why": s["it"].get("ref_why")})
                self.st = None

    eng.add_strategy(Harness()); eng.run(); eng.dispose()
    return trades, skipped + 0 * len(voids), len(voids)


def summarize(trades, split_ts, key="net_r"):
    def s(t):
        n = len(t); rs = [x[key] for x in t]
        return {"n": n, "win_rate": sum(r > 0 for r in rs) / n if n else 0.0, "expectancy_r": sum(rs) / n if n else 0.0}
    return {"full": s(trades), "oos": s([t for t in trades if t["entry_ts"] >= split_ts])}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--intents", required=True); ap.add_argument("--variant", default="parity")
    ap.add_argument("--out", default=None); ap.add_argument("--split", type=float, default=0.6)
    a = ap.parse_args(); spec = json.load(open(a.intents))
    allt, skipped, voids, t0, t1 = [], 0, 0, None, None
    for sym in spec["symbols"]:
        rows = json.load(open(os.path.join(spec["data_dir"], f"candles_{sym}_60.json")))
        t0 = rows[0]["start"] if t0 is None else min(t0, rows[0]["start"]); t1 = rows[-1]["start"] if t1 is None else max(t1, rows[-1]["start"])
        its = [i for i in spec["intents"] if i["symbol"] == sym]
        tr, sk, vd = run_symbol(sym, rows, its, a.variant, spec.get("taker_fee", 0.0009)); allt += tr; skipped += sk; voids += vd
    split = t0 + (t1 - t0) * a.split
    ref = [{"entry_ts": i["entry_ts"], "net_r": i["ref_net_r"]} for i in spec["intents"]]
    # concordância por trade (mesma entrada)
    m = {(i["symbol"], i["entry_ts"]): i for i in spec["intents"]}
    same_why = sum(1 for t in allt if (t["why"] == "TP") == (str(m[(t["symbol"], t["entry_ts"])]["ref_why"]).startswith(("TAKE_PROFIT", "ROI"))))
    diffs = sorted(abs(t["net_r_slip"] - t["ref_net_r"]) for t in allt)
    rep = {"spec": spec["spec"], "variant": a.variant, "data_dir": spec["data_dir"], "symbols": spec["symbols"],
           "intents": len(spec["intents"]), "skipped_overlap": skipped, "void_entries": voids, "nautilus_trades": len(allt),
           "reference": summarize(ref, split), "nautilus_fees_only": summarize(allt, split, "net_r"),
           "nautilus_plus_desk_slippage": summarize(allt, split, "net_r_slip"),
           "per_trade_abs_diff_r": {"median": diffs[len(diffs) // 2] if diffs else None, "p90": diffs[int(len(diffs) * 0.9)] if diffs else None},
           "exit_type_agreement": same_why / len(allt) if allt else None}
    if a.out: json.dump({**rep, "trades": allt}, open(a.out, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
