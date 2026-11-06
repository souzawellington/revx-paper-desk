"""Bots Scalp (paper only): spec congelado, motor (enchimento maker por atravessamento, stop taker, alvo, custos, kill diário),
isolamento (sem broker/live/chaves), forward com recuperação após reinício, resumo horário sem spam, snapshot."""
import copy, inspect, json, math, os
import pytest

from desk.scalp import engine as E, spec as SP, feed as F, run as R, ind as I
from desk.scalp.engine import Engine, new_state, M1, D, SYMS, BOOKS

T0 = 1792022400000            # 2026-10-14T00:00Z (múltiplo de 1 dia)
HS = 0.0001


def flat(c, v=0.0): return {"o": c, "h": c, "l": c, "c": c, "v": v}


def mk(state=None):
    tr, ev = [], []
    st = state or new_state(0)
    return Engine(st, lambda s, t: HS, on_trade=tr.append, on_event=ev.append), st, tr, ev


def pend(eng, st, book="bb_rsi", sym="BTC-USD", L=100.0, d=0.004, tp=None, ts=T0, qty=0.1):
    b = st["books"][book]; stop = L * (1 - d)
    per_unit = (L - stop) + stop * (0.0009 + 0.001 + HS)
    b["pend"][sym] = {"id": 1, "limit": L, "qty": qty, "reserve": qty * L, "stop": stop, "tp": tp or L * (1 + 1.5 * d), "d": d,
                      "r_unit": qty * per_unit, "signal_ts": ts, "expiry": ts + 3 * M1, "atr": 0.1, "adx": 10}
    b["cash"] -= qty * L


def bars(**over):
    out = {s: flat(100.0) for s in SYMS}; out.update(over); return out


# ---------- spec / prereg ----------
def test_prereg_frozen_and_matches_code():
    assert SP.check() == SP.spec_hash()
    doc = json.load(open(SP.PREREG)); assert doc["spec"]["id"] == "scalp_forward_v1"


def test_prereg_refuses_on_spec_change(monkeypatch):
    s2 = copy.deepcopy(SP.SPEC); s2["risk"]["risk_pct"] = 0.01
    monkeypatch.setattr(SP, "SPEC", s2)
    with pytest.raises(RuntimeError): SP.check()


def test_user_rules_in_spec():
    r, x = SP.SPEC["risk"], SP.SPEC["execution"]
    assert r["risk_pct"] == 0.005 and r["stop_fixed"] == 0.004 and r["stop_atr_mult"] == 1.5 and r["rr_min"] == 1.5
    assert r["daily_kill"] == 0.02 and r["max_open"] == 5 and r["start_equity"] == 65.0 and r["ceiling"] == 1000.0
    assert x["taker_fee"] == 0.0009 and x["maker_fee"] == 0.0 and x["slippage"] == 0.001
    assert SP.SPEC["symbols"] == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert set(BOOKS) == {"bb_rsi", "bb_rsi_adx", "ema_pb", "ema_pb_adx", "brk", "brk_adx"}


# ---------- isolamento ----------
def test_paper_only_isolation():
    assert E.BROKER is None
    for mod in (E, R, F, SP, I):
        src = inspect.getsource(mod)
        assert "import live" not in src and "from live" not in src and "bot.revolutx" not in src and "bot.brokers" not in src
        assert "/orders" not in src and "X-Revx-Signature" not in src and "private_key" not in src
        assert "execution_mode" not in src.replace("não lê nem muda execution_mode", "")
    assert "api/1.0/public/candles" in F.RX1 + "/public/candles"


# ---------- indicadores ----------
def test_indicators_basic():
    P = SP.SPEC["indicators"]; t = I.TFInd(P); v = None
    for k in range(80): v = t.update({"o": 100 + k, "h": 101 + k, "l": 99 + k, "c": 100 + k, "v": 1})
    assert v["rsi"] == 100.0 and v["ema_fast"] > v["ema_slow"] and abs(v["atr"] - 2.0) < 1e-6 and v["ready"]
    t2 = I.TFInd(P, json.loads(json.dumps(t.dump())))     # serialização = mesmo resultado
    b = {"o": 180, "h": 181, "l": 179, "c": 179.5, "v": 1}
    assert t.update(b) == t2.update(b)


# ---------- execução ----------
def test_limit_fills_only_when_traded_through():
    eng, st, tr, _ = mk(); pend(eng, st)
    eng.step(T0, bars(**{"BTC-USD": {"o": 100.2, "h": 100.3, "l": 100.0, "c": 100.1, "v": 1}}))   # toca, não atravessa
    assert "BTC-USD" in st["books"]["bb_rsi"]["pend"] and not st["books"]["bb_rsi"]["pos"]
    eng.step(T0 + M1, bars(**{"BTC-USD": {"o": 100.1, "h": 100.2, "l": 99.99, "c": 100.05, "v": 1}}))
    p = st["books"]["bb_rsi"]["pos"]["BTC-USD"]; assert p["entry"] == 100.0


def test_unfilled_limit_expires_and_releases_cash():
    eng, st, tr, _ = mk(); pend(eng, st)
    for k in range(4): eng.step(T0 + k * M1, bars())
    b = st["books"]["bb_rsi"]; assert not b["pend"] and b["n"]["unfilled"] == 1 and abs(b["cash"] - 65.0) < 1e-9


def test_stop_is_taker_with_slippage_and_spread():
    eng, st, tr, _ = mk(); pend(eng, st)
    eng.step(T0, bars(**{"BTC-USD": {"o": 100.0, "h": 100.0, "l": 99.9, "c": 99.95, "v": 1}}))    # enche
    eng.step(T0 + M1, bars(**{"BTC-USD": {"o": 99.9, "h": 99.9, "l": 99.5, "c": 99.55, "v": 1}}))  # stop 99.6
    t = tr[-1]; assert t["reason"] == "stop"
    exp_px = 99.6 * (1 - 0.001 - HS); assert abs(t["exit"] - exp_px) < 1e-9
    assert abs(t["fee"] - 0.1 * exp_px * 0.0009) < 1e-12 and t["slip_cost"] > 0
    assert -1.0001 < t["r"] < -0.999                         # perda no stop = exactamente 1R (custos incluídos)


def test_gap_below_stop_exits_at_open():
    eng, st, tr, _ = mk(); pend(eng, st)
    eng.step(T0, bars(**{"BTC-USD": {"o": 100.0, "h": 100.0, "l": 99.9, "c": 99.95, "v": 1}}))
    eng.step(T0 + M1, bars(**{"BTC-USD": {"o": 99.0, "h": 99.1, "l": 98.9, "c": 99.0, "v": 1}}))
    assert abs(tr[-1]["exit"] - 99.0 * (1 - 0.001 - HS)) < 1e-9 and tr[-1]["r"] < -1


def test_target_is_maker_and_never_on_fill_bar():
    eng, st, tr, _ = mk(); pend(eng, st)
    eng.step(T0, bars(**{"BTC-USD": {"o": 100.0, "h": 101.0, "l": 99.9, "c": 100.5, "v": 1}}))    # enche; high > alvo ignorado
    assert not tr
    eng.step(T0 + M1, bars(**{"BTC-USD": {"o": 100.5, "h": 100.61, "l": 100.4, "c": 100.5, "v": 1}}))
    t = tr[-1]; assert t["reason"] == "alvo (maker)" and t["fee"] == 0 and t["exit"] == pytest.approx(100.6) and 0.95 < t["r"] < 1.05   # 1,5×d em preço ≈ 1R líquido (R inclui custos do stop)


def test_stop_wins_when_stop_and_target_same_bar():
    eng, st, tr, _ = mk(); pend(eng, st)
    eng.step(T0, bars(**{"BTC-USD": {"o": 100.0, "h": 100.0, "l": 99.9, "c": 99.95, "v": 1}}))
    eng.step(T0 + M1, bars(**{"BTC-USD": {"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 1}}))
    assert tr[-1]["reason"] == "stop"


def test_stop_is_tighter_of_fixed_and_atr_and_cost_filter():
    eng, st, tr, _ = mk(); b = st["books"]["brk"]
    v = {"atr": 0.1, "adx": 30}                                   # 1.5×0.1/100 = 0.15% < 0.4%
    eng._place(b, "BTC-USD", "brk", v, flat(100.0), T0, 1)
    q = b["pend"]["BTC-USD"]; assert q["d"] == pytest.approx(0.0015) and q["tp"] == pytest.approx(100 * (1 + 1.5 * 0.0015))
    b2 = st["books"]["ema_pb"]; eng._place(b2, "ETH-USD", "ema_pb", {"atr": 1.0}, flat(100.0), T0, 5)
    assert b2["pend"]["ETH-USD"]["d"] == pytest.approx(0.004)           # ATR largo → 0,4% fixo
    b3 = st["books"]["bb_rsi"]; eng._place(b3, "SOL-USD", "bb_rsi", {"atr": 0.05, "bb_mid": 100.01}, flat(100.0), T0, 1)
    assert "SOL-USD" not in b3["pend"] and b3["n"]["rej_cost"] == 1    # alvo 0,075% < custos ~0,21% → rejeitado
    b4 = st["books"]["bb_rsi_adx"]; eng._place(b4, "SOL-USD", "bb_rsi", {"atr": 0.0, "bb_mid": 101}, flat(100.0), T0, 1)
    assert b4["n"]["rej_cost"] == 1                                     # d = 0 → rejeitado


def test_sizing_risk_half_pct_and_cap_20pct():
    eng, st, _, _ = mk(); b = st["books"]["brk"]
    eng._place(b, "BTC-USD", "brk", {"atr": 0.25}, flat(100.0), T0, 1)    # d 0,375%
    q = b["pend"]["BTC-USD"]
    assert q["qty"] * 100 <= 0.2 * 65 + 1e-9 and q["r_unit"] <= 0.005 * 65 + 1e-9


def test_daily_kill_halts_until_next_utc_day():
    eng, st, tr, ev = mk(); b = st["books"]["bb_rsi"]
    eng.step(T0, bars()); b["pos"]["BTC-USD"] = {"id": 9, "entry": 100.0, "qty": 0.6, "stop": 50.0, "tp": 200.0, "d": 0.004,
                                                 "r_unit": 1, "signal_ts": T0, "fill_ts": T0, "bars_held": 0}
    b["cash"] -= 60.0
    eng.step(T0 + M1, bars(**{"BTC-USD": flat(97.0)}))         # −1,8 USD = −2,8%
    assert b["halted_until"] == T0 // D + 1 and not b["pos"] and ev[-1]["type"] == "daily_kill"
    assert tr[-1]["reason"].startswith("kill diário")
    eng.step(T0 + D, bars()); assert b["halted_until"] is None


def test_regime_filter_books_separate():
    v = {"adx": 15.0}; assert Engine._regime_ok("bb_rsi", v) and not Engine._regime_ok("ema_pb", v)
    v = {"adx": 30.0}; assert not Engine._regime_ok("bb_rsi", v) and Engine._regime_ok("brk", v)


def test_short_signal_only_exits_long():
    v = {"bb_hi": 101, "rsi": 80}; assert Engine._short_exit("bb_rsi", v, flat(102))
    assert Engine._short_exit("ema_pb", {"ema_slow": 101, "ema_fast": 102}, flat(100))
    assert Engine._short_exit("brk", {"prev_range_lo": 99}, flat(98.5))


def test_metrics_verdicts():
    t = lambda pnl, r: {"pnl": pnl, "r": r, "fee": 0, "slip_cost": 0, "stop_pct": 0.004, "notional": 10, "reason": "stop"}
    assert E.metrics([t(1, 1)] * 10, {"max_dd": 0.01})["verdict"] == "dados insuficientes"
    assert E.metrics([t(1, 2.0)] * 20 + [t(-1, -1)] * 20, {"max_dd": 0.05})["verdict"] == "possível GO (só paper)"
    assert E.metrics([t(1, 0.5)] * 10 + [t(-1, -1)] * 30, {"max_dd": 0.05})["verdict"] == "NO-GO"


# ---------- forward (rede falsa) ----------
class FakeAPI:
    def __init__(self, now, skip=()):
        self.now, self.skip, self.calls = now, set(skip), []

    def __call__(self, url, params=None):
        self.calls.append(url)
        if "order-book" in url:
            return {"data": {"bids": [{"price": "99.99"}], "asks": [{"price": "100.01"}]}}
        a, b = params["since"], params["until"]; out = []
        for ts in range(a - a % M1, b + 1, M1):
            if ts > self.now - M1 or ts in self.skip or ts < a: continue
            c = 100 + math.sin(ts / M1 / 7.0)
            out.append({"start": ts, "open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 1})
        return {"data": out}


def test_forward_warmup_resume_and_missing_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    now = [T0 + 2000 * M1 + 30_000]
    api = FakeAPI(now[0], skip={T0 + 2003 * M1})
    f = R.Forward(get=api, clock=lambda: now[0], log=lambda *a: None)
    r = f.run_once(); assert r["ok"], r
    st = json.load(open(tmp_path / "forward" / "state.json"))
    assert st["trade_from"] == T0 + 2000 * M1 and st["warm_bars"] > 900
    now[0] += 10 * M1; api.now = now[0]
    f2 = R.Forward(get=api, clock=lambda: now[0], log=lambda *a: None)      # "reinício"
    r = f2.run_once(); assert r["ok"], r
    st = json.load(open(tmp_path / "forward" / "state.json"))
    assert st["last_ts"] == (now[0] - M1 - 20_000) // M1 * M1
    assert any("order-book" in u for u in api.calls)
    meta = json.load(open(tmp_path / "forward" / "meta.json"))
    assert meta["spreads"]["BTC-USD"]["half_spread"] == pytest.approx(0.0001, rel=1e-3)
    assert not [u for u in api.calls if "/orders" in u or "balances" in u]


def test_forward_api_failure_does_not_advance(tmp_path, monkeypatch):
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    now = T0 + 2000 * M1; api = FakeAPI(now)
    f = R.Forward(get=api, clock=lambda: now, log=lambda *a: None); f.run_once()
    last = json.load(open(tmp_path / "forward" / "state.json"))["last_ts"]
    f.get = lambda u, p=None: None; f.clock = lambda: now + 5 * M1
    r = f.run_once(); assert not r["ok"] and f.meta["health"]["consec_fail"] == 1
    assert json.load(open(tmp_path / "forward" / "state.json"))["last_ts"] == last


def test_summary_at_most_one_per_hour_and_only_if_new(tmp_path, monkeypatch):
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    f = R.Forward(get=FakeAPI(T0), clock=lambda: T0, log=lambda *a: None); sent = []
    assert f.maybe_summary(T0, emit=sent.append) is None                 # nada novo → nada
    tr = {k: 0 for k in R.TRADE_COLS}; tr.update(book="bb_rsi", symbol="BTC-USD", reason="stop", catchup=False, pnl=-0.1, r=-1)
    R.append_csv(os.path.join(R.sdir("forward"), "trades.csv"), R.TRADE_COLS, [tr])
    a = f.maybe_summary(T0 + 60_000, emit=sent.append)
    assert a["type"] == "SCALP_SUMMARY" and a["id"].startswith("SCALP_SUMMARY:") and a["reply_options"] == [] and a["autonomous"]
    assert "SIMULADO" in a["text"]
    R.append_csv(os.path.join(R.sdir("forward"), "trades.csv"), R.TRADE_COLS, [tr])
    assert f.maybe_summary(T0 + 120_000, emit=sent.append) is None      # mesma hora → não repete
    assert f.maybe_summary(T0 + 3_600_000, emit=sent.append) is not None and len(sent) == 2


def test_grid_fills_missing_minutes():
    rows = [{"ts": T0, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}, {"ts": T0 + 2 * M1, "o": 2, "h": 2, "l": 2, "c": 2, "v": 1}]
    g, syn = F.grid(rows, T0, T0 + 3 * M1, None)
    assert [r["c"] for r in g] == [1, 1, 2, 2] and syn == 2 and g[1]["v"] == 0


def test_box_freeze_gap_is_backfilled_bar_by_bar_and_catchup_counted(tmp_path, monkeypatch):
    """Pausa do box (~50 min sem correr o ciclo): ao acordar recupera TODAS as velas reais em falta, sem saltar minutos,
    marca o reprocessamento como catchup e o status mostra quantos trades forward são catchup."""
    monkeypatch.setenv("SCALP_STATE_DIR", str(tmp_path))
    now = [T0 + 2000 * M1 + 30_000]; api = FakeAPI(now[0])
    f = R.Forward(get=api, clock=lambda: now[0], log=lambda *a: None); assert f.run_once()["ok"]
    last0 = json.load(open(tmp_path / "forward" / "state.json"))["last_ts"]
    stepped, flags = [], []
    orig = E.Engine.step
    def spy(self, ts, bars_):
        stepped.append(ts); flags.append(self.catchup); assert not any(b.get("syn") for b in bars_.values())
        return orig(self, ts, bars_)
    monkeypatch.setattr(E.Engine, "step", spy)
    now[0] += 50 * M1; api.now = now[0]                       # box congelado 50 min
    assert f.run_once()["ok"]
    st = json.load(open(tmp_path / "forward" / "state.json"))
    assert st["last_ts"] == (now[0] - M1 - 20_000) // M1 * M1
    assert stepped == list(range(last0 + M1, st["last_ts"] + M1, M1))     # minuto a minuto, sem buracos
    assert flags[0] and not flags[-1]                                      # velas antigas = catchup; a mais recente não
    tr = {k: 0 for k in R.TRADE_COLS}; tr.update(book="bb_rsi", symbol="BTC-USD", reason="stop", pnl=-0.1, r=-1)
    R.append_csv(os.path.join(R.sdir("forward"), "trades.csv"), R.TRADE_COLS, [dict(tr, catchup=True), dict(tr, catchup=False)])
    T = R.read_trades("forward"); rep = R.report("forward")
    for b in BOOKS:
        tb = [t for t in T if t["book"] == b]
        assert rep[b]["trades"] == len(tb) and rep[b]["catchup_trades"] == sum(1 for t in tb if t["catchup"])
    assert rep["bb_rsi"]["trades"] - rep["bb_rsi"]["catchup_trades"] >= 1 and rep["bb_rsi"]["catchup_trades"] >= 1
