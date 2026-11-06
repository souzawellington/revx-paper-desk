"""Livros EMS (paper only, ems_v1): sem look-ahead, maker só por atravessamento, maker-first/regra taker 0,35%, rejeição por custo,
kill DD 20%, teto $1.000 trancado, Decimal, OBI sem catchup, sem chaves/broker, forward com recuperação após pausa, status, painel."""
import copy, inspect, json, math, os, random
from decimal import Decimal
import pytest

from desk.ems import engine as E, spec as SP, run as R, ind as I
from desk.ems.engine import Engine, Ctx, new_state, new_book, to_json, from_json, M1, D, SYMS, BOOKS, TRAINING, HALTED, CEILING

T0 = 1792022400000            # 2026-10-14T00:00Z


def series(n=900, seed=7, vol=0.0015):
    random.seed(seed); out = {}
    for s, p0 in (("BTC-USD", 80000.0), ("ETH-USD", 4000.0), ("SOL-USD", 190.0)):
        p, rows = p0, []
        for i in range(n):
            o = p; p = p * math.exp(random.gauss(0, vol))
            h = max(o, p) * (1 + abs(random.gauss(0, vol / 3))); l = min(o, p) * (1 - abs(random.gauss(0, vol / 3)))
            rows.append({"ts": T0 + i * M1, "o": o, "h": h, "l": l, "c": p, "v": random.random() * 10})
        out[s] = rows
    return out


def run_engine(S, upto=None, trade_from=0, ctx=None):
    tr, ev = [], []
    st = new_state(trade_from); eng = Engine(st, on_trade=tr.append, on_event=ev.append)
    n = len(S[SYMS[0]]) if upto is None else upto
    for i in range(n): eng.step(S[SYMS[0]][i]["ts"], {s: S[s][i] for s in SYMS}, ctx or Ctx())
    eng.dump(); return st, tr, ev


def flat(c, v=1.0): return {"o": c, "h": c, "l": c, "c": c, "v": v}


def with_pend(kind="maker", L=D("100"), d=D("0.005"), book="ems_vwap_mr", sym="BTC-USD", qty=D("0.1"), ts=T0):
    st = new_state(0); b = st["books"][book]
    b["pend"][sym] = {"setup": "X", "kind": kind, "limit": L if kind == "maker" else None, "qty": qty, "reserve": qty * L,
                      "d": d, "stop": L * (1 - d), "tp": L * (1 + 2 * d), "signal_ts": ts, "active_from": ts + M1, "expiry": ts + 4 * M1}
    b["cash"] -= qty * L
    st["last_ts"] = ts; st["last_close"] = {s: "100" for s in SYMS}
    tr = []; return st, Engine(st, on_trade=tr.append), tr


def bars(sym_bar, sym="BTC-USD"):
    out = {s: flat(100.0) for s in SYMS}; out[sym] = sym_bar; return out


# ---------------- spec / isolamento ----------------
def test_spec_frozen_and_locked_rules():
    S = SP.SPEC
    assert S["risk"]["start_equity"] == "65" and S["risk"]["ceiling"] == "1000" and S["risk"]["dd_kill"] == "0.20"
    assert S["execution"]["maker_fee"] == "0" and S["execution"]["taker_fee"] == "0.0009" and S["execution"]["taker_min_edge"] == 0.0035
    assert 0.005 <= float(S["risk"]["risk_pct"]) <= 0.01 and S["auditor"]["min_trades"] == 40
    assert len(SP.spec_hash()) == 64 and len(SP.code_hash()) == 64
    assert [b["entry_mode"] for b in S["books"].values()].count("taker_if_edge") == 1


def test_prereg_check_matches_repo_freeze():
    assert SP.check() == SP.spec_hash()


def _code_only(src):
    import ast
    t = ast.parse(src)
    for n in ast.walk(t):
        body = getattr(n, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            body[0] = ast.Pass()
    return ast.unparse(t)


def test_no_broker_no_keys_no_live():
    assert E.BROKER is None
    for mod in (E, R, I, SP):
        src = inspect.getsource(mod)
        code = _code_only(src)
        assert "revolutx" not in code and "private" not in code and "execution_mode" not in code and "desk.live" not in code
        assert "place_order" not in code and "sign(" not in code and "REVX_API_KEY" not in code
    src = inspect.getsource(R)
    assert "/api/2.0/public" in src.replace("{feed.RX2}", "/api/2.0") or "public/order-book" in src
    import desk.ems.__main__ as M
    assert "REVX_API_KEY" in inspect.getsource(M) and "pop" in inspect.getsource(M)


# ---------------- execução ----------------
def test_maker_fills_only_when_price_crosses():
    st, eng, tr = with_pend()
    eng.step(T0 + M1, bars({"o": 100.5, "h": 101, "l": 100.0, "c": 100.4, "v": 1}))       # toca mas não atravessa
    assert "BTC-USD" in st["books"]["ems_vwap_mr"]["pend"]
    eng.step(T0 + 2 * M1, bars({"o": 100.3, "h": 100.4, "l": 99.9, "c": 100.2, "v": 1}))   # atravessa
    p = st["books"]["ems_vwap_mr"]["pos"]["BTC-USD"]
    assert p["entry"] == D("100") and p["entry_fee"] == 0 and p["kind"] == "maker"


def test_pending_expires_after_valid_bars_and_refunds():
    st, eng, tr = with_pend()
    for k in range(1, 5): eng.step(T0 + k * M1, bars(flat(101.0)))
    b = st["books"]["ems_vwap_mr"]
    assert not b["pend"] and not b["pos"] and b["cash"] == D("65") and b["n"]["unfilled"] == 1


def test_stop_beats_target_same_bar_and_exit_costs():
    st, eng, tr = with_pend()
    eng.step(T0 + M1, bars({"o": 100.2, "h": 100.3, "l": 99.95, "c": 100.1, "v": 1}))
    eng.step(T0 + 2 * M1, bars({"o": 100.0, "h": 102.0, "l": 99.0, "c": 100.0, "v": 1}))   # bate SL e TP
    assert len(tr) == 1 and tr[0]["reason"] == "stop"
    t = tr[0]; assert t["exit"] < t["stop"] and t["fee"] > 0 and t["pnl"] < 0 and isinstance(t["pnl"], Decimal)
    assert -1.05 < float(t["r"]) < -0.95


def test_target_fills_maker_only_on_cross():
    st, eng, tr = with_pend()
    eng.step(T0 + M1, bars({"o": 100.2, "h": 100.3, "l": 99.95, "c": 100.1, "v": 1}))
    eng.step(T0 + 2 * M1, bars({"o": 100.5, "h": 101.0, "l": 100.4, "c": 100.9, "v": 1}))   # h == tp: não atravessa
    assert not tr
    eng.step(T0 + 3 * M1, bars({"o": 100.9, "h": 101.2, "l": 100.8, "c": 101.1, "v": 1}))
    assert tr[0]["reason"].startswith("alvo") and tr[0]["exit"] == D("101.000") and float(tr[0]["r"]) > 1.3


def test_taker_fills_next_open_with_slippage_and_fee():
    st, eng, tr = with_pend(kind="taker", book="ems_squeeze_bo", d=D("0.01"))
    eng.step(T0 + M1, bars({"o": 100.0, "h": 100.2, "l": 99.8, "c": 100.1, "v": 1}))
    p = st["books"]["ems_squeeze_bo"]["pos"]["BTC-USD"]
    assert p["entry"] > D("100.1") and p["entry_fee"] > 0 and p["stop"] == p["entry"] * D("0.99")


class _V(dict):
    pass


def place(book, atr_bps, hs="0.0001"):
    st = new_state(0); eng = Engine(st)
    v = {"atr_bps": atr_bps}
    ctx = Ctx(hs=lambda s, t: D(hs))
    eng._place(book, st["books"][book], "BTC-USD", "X", v, {"c": D("100")}, T0, T0 + M1, ctx)
    return st["books"][book]


def test_maker_first_reversions_never_taker():
    b = place("ems_vwap_mr", 80.0)                 # d=1,2%: TP 2,4% ≫ custos, mas reversão é sempre maker
    assert b["pend"]["BTC-USD"]["kind"] == "maker"


def test_taker_only_when_edge_above_035_after_costs():
    b = place("ems_squeeze_bo", 80.0)              # tp 2,4% − 2×(0,09+0,10+0,01)% = 2,0% > 0,35% → taker
    assert b["pend"]["BTC-USD"]["kind"] == "taker"
    b = place("ems_squeeze_bo", 22.0)              # d=0,33%, tp 0,66% − 0,40% = 0,26% < 0,35% → maker
    assert b["pend"]["BTC-USD"]["kind"] == "maker"


def test_reject_when_target_does_not_cover_costs():
    b = place("ems_vwap_mr", 10.0, hs="0.0005")    # d=0,30% (piso) → TP 0,60% ≤ 0,09+0,10+2×0,05 = 0,29%? não: cobre
    assert b["pend"]
    b = place("ems_vwap_mr", 10.0, hs="0.0012")    # TP 0,60% ≤ 0,09+0,10+0,24 = 0,43%? cobre ainda
    assert b["pend"]
    b = place("ems_vwap_mr", 10.0, hs="0.0021")    # 0,60% ≤ 0,19% + 0,42% = 0,61% → rejeita
    assert not b["pend"] and b["n"]["rej_cost"] == 1


def test_stop_floor_and_risk_sizing():
    b = place("ems_vwap_mr", 5.0)
    q = b["pend"]["BTC-USD"]
    assert q["d"] == D("0.003")                    # piso 0,30% (corrige o stop minúsculo dominado por custos)
    assert q["qty"] * q["limit"] <= D("65") * D("0.33") + D("0.01")


# ---------------- kill / teto ----------------
def test_dd_kill_halts_and_locks():
    st, eng, tr = with_pend(qty=D("0.2"))
    ev = []; eng.on_event = ev.append
    eng.step(T0 + M1, bars({"o": 100.2, "h": 100.3, "l": 99.95, "c": 100.1, "v": 1}))
    b = st["books"]["ems_vwap_mr"]; b["cash"] -= D("15")            # perda forçada → equity ~53 < 0,8×65
    eng.step(T0 + 2 * M1, bars(flat(100.1)))
    assert b["state"] == HALTED and not b["pos"] and ev and ev[0]["type"] == HALTED
    for k in range(3, 300): eng.step(T0 + k * M1, bars(flat(100.1)))
    assert b["state"] == HALTED and b["n"]["placed"] == 0


def test_ceiling_pauses_and_needs_manual_rebase(tmp_path, monkeypatch):
    st = new_state(0); eng = Engine(st); ev = []; eng.on_event = ev.append
    st["books"]["ems_rsi_div"]["cash"] = D("1000.5"); st["books"]["ems_rsi_div"]["peak"] = D("1000.5")
    eng.step(T0, {s: flat(100.0) for s in SYMS})
    assert st["books"]["ems_rsi_div"]["state"] == CEILING and ev[0]["type"] == CEILING
    monkeypatch.setenv("EMS_STATE_DIR", str(tmp_path))
    R._atomic_json(os.path.join(R.fdir(), "state.json"), to_json(st))
    with pytest.raises(SystemExit): R.rebase("ems_rsi_div")                # sem --confirm
    with pytest.raises(SystemExit): R.rebase("ems_vwap_mr", confirm=True)  # livro em treino
    nb = R.rebase("ems_rsi_div", confirm=True)
    assert nb["equity"] == D("65") and nb["state"] == TRAINING and nb["cycles"] == 1


def test_never_sweeps_or_withdraws():
    src = inspect.getsource(E) + inspect.getsource(R)
    assert "withdraw" not in src.lower() and "deposit" not in src.lower() and "sweep" not in src.lower()


# ---------------- Decimal / serialização ----------------
def test_decimal_roundtrip_exact():
    st, eng, tr = with_pend()
    eng.step(T0 + M1, bars({"o": 100.2, "h": 100.3, "l": 99.95, "c": 100.1, "v": 1})); eng.dump()
    j = json.loads(json.dumps(to_json(st)))
    back = from_json(j)
    b = back["books"]["ems_vwap_mr"]
    assert isinstance(b["cash"], Decimal) and isinstance(b["pos"]["BTC-USD"]["qty"], Decimal)
    assert to_json(back) == j


# ---------------- sem look-ahead ----------------
def test_no_lookahead_future_bars_do_not_change_past():
    S = series(700)
    st_a, tr_a, _ = run_engine(S, upto=500)
    S2 = copy.deepcopy(S)
    for s in SYMS:
        for r in S2[s][500:]: r.update(o=r["o"] * 1.3, h=r["h"] * 1.3, l=r["l"] * 1.3, c=r["c"] * 1.3)
    st_b, tr_b, _ = run_engine(S2, upto=500)
    assert to_json(st_a) == to_json(st_b) and tr_a == tr_b
    _, tr_full, _ = run_engine(S2)
    cut = T0 + 500 * M1
    assert [t for t in tr_full if t["exit_ts"] < cut] == tr_a


def test_obi_book_never_enters_in_catchup_or_without_fresh_book():
    S = series(800, seed=3, vol=0.003)
    good = {"ts": 0, "obi": 0.9, "spread_bps": 1.0}
    st, tr, _ = run_engine(S, ctx=Ctx(book=lambda s, t: dict(good, ts=t), catchup=True))
    b = st["books"]["ems_vwap_obi"]
    assert b["n"]["placed"] == 0 and b["n"]["rej_no_book"] == b["n"]["signals"] - b["n"]["rej_shock"] - b["n"]["rej_busy"] - b["n"]["rej_macro"]
    st2, _, _ = run_engine(S, ctx=Ctx(book=lambda s, t: dict(good, ts=t - 10 * 60_000)))
    assert st2["books"]["ems_vwap_obi"]["n"]["placed"] == 0
    st3, _, _ = run_engine(S, ctx=Ctx(book=lambda s, t: dict(good, ts=t)))
    assert st3["books"]["ems_vwap_obi"]["n"]["placed"] == st3["books"]["ems_vwap_mr"]["n"]["placed"] > 0


def test_macro_risk_off_blocks_entries():
    S = series(800, seed=3, vol=0.003)
    st, _, _ = run_engine(S, ctx=Ctx(macro=lambda t: "RISK_OFF"))
    for b in BOOKS: assert st["books"][b]["n"]["placed"] == 0
    assert sum(st["books"][b]["n"]["rej_macro"] for b in BOOKS) > 0


def test_indicator_state_serializable_and_equivalent():
    S = series(400)
    a = I.EMSInd(SP.SPEC["indicators"], None)
    for r in S["BTC-USD"][:200]: a.update(r)
    b = I.EMSInd(SP.SPEC["indicators"], json.loads(json.dumps(a.dump())))
    for r in S["BTC-USD"][200:]:
        assert a.update(r) == b.update(r)


# ---------------- forward (rede falsa) ----------------
def fake_api(S, clock):
    idx = {s: {r["ts"]: r for r in S[s]} for s in SYMS}
    def get(url, params=None):
        if "order-book" in url:                        # meio-spread igual ao fallback do spec → contínuo e catchup comparáveis ao cêntimo
            x = 100 * float(SP.SPEC["execution"]["fallback_half_spread"][url.rsplit("/", 1)[1]])
            return {"data": {"bids": [{"price": str(100 - x), "quantity": "3"}] * 5, "asks": [{"price": str(100 + x), "quantity": "1"}] * 5}}
        assert "/public/" in url
        s = url.rsplit("/", 1)[1]; a, b = params["since"], params["until"]
        return {"data": [{"start": t, "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"], "volume": r["v"]}
                         for t, r in idx[s].items() if a <= t <= b and t + M1 + 80_000 <= clock["now"]]}
    return get


def fwd(tmp_path, monkeypatch, S, start_i):
    monkeypatch.setenv("EMS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SP, "check", lambda *a, **k: "t" * 64)
    clock = {"now": T0 + start_i * M1 + 85_000}
    return R.Forward(get=fake_api(S, clock), clock=lambda: clock["now"], log=lambda *a: None, macro=lambda t: "OK"), clock


def test_forward_pause_catchup_equals_continuous(tmp_path, monkeypatch):
    S = series(2200, seed=11, vol=0.0025)
    f, clock = fwd(tmp_path / "a", monkeypatch, S, 1000)
    assert f.run_once()["ok"]
    for k in range(1, 1100):
        clock["now"] += M1; assert f.run_once()["ok"]
    cont = R.read_trades(str(tmp_path / "a" / "forward"))
    g, clock2 = fwd(tmp_path / "b", monkeypatch, S, 1000)
    assert g.run_once()["ok"]
    clock2["now"] += 1099 * M1                                     # box em pausa ~18 h e volta
    assert g.run_once()["ok"]
    pause = R.read_trades(str(tmp_path / "b" / "forward"))
    key = lambda t: (t["book"], t["symbol"], t["fill_ts"], t["exit_ts"], t["reason"], round(t["pnl"], 6))
    assert [key(t) for t in cont if t["book"] != "ems_vwap_obi"] == [key(t) for t in pause if t["book"] != "ems_vwap_obi"]
    assert all(t["catchup"] for t in pause) and not any(t["book"] == "ems_vwap_obi" for t in pause)
    st = json.load(open(tmp_path / "b" / "forward" / "state.json"))
    assert st["last_ts"] == json.load(open(tmp_path / "a" / "forward" / "state.json"))["last_ts"]


def test_forward_handles_api_failure_without_advancing(tmp_path, monkeypatch):
    S = series(1300)
    f, clock = fwd(tmp_path, monkeypatch, S, 1000)
    assert f.run_once()["ok"]
    last = json.load(open(tmp_path / "forward" / "state.json"))["last_ts"]
    f.get = lambda url, params=None: None
    clock["now"] += 5 * M1
    r = f.run_once(); assert not r["ok"] and f.meta["health"]["consec_fail"] == 1
    assert json.load(open(tmp_path / "forward" / "state.json"))["last_ts"] == last


def test_loop_hook_never_raises(monkeypatch):
    class Boom:
        def run_once(self): raise RuntimeError("x")
    monkeypatch.setitem(R._HOOK, "fwd", Boom())
    assert R.loop_hook(lambda *a: None)["ok"] is False


def test_scalp_loop_calls_ems_hook_isolated():
    from desk.scalp import run as SR
    src = inspect.getsource(SR.loop)
    assert "loop_hook" in src and "except Exception" in src


# ---------------- status / painel ----------------
def test_status_and_dashboard_data_clean(tmp_path, monkeypatch):
    S = series(1400, seed=5, vol=0.003)
    f, clock = fwd(tmp_path, monkeypatch, S, 1000)
    f.run_once(); clock["now"] += 300 * M1; f.run_once()
    s = R.status(); txt = R.fmt_status(s)
    assert "PAPER ONLY" in txt and all(b in txt for b in BOOKS)
    for b in BOOKS: assert s["forward"]["books"][b]["state"] == TRAINING
    d = R.dashboard_data()
    assert d["available"] and len(d["cards"]) == 4 and set(d["candles"]) == set(SYMS)
    from bot.public_snapshot import sanitize, assert_clean
    assert sanitize(d) == json.loads(json.dumps(d)) and assert_clean({"ems": d}, secrets=[])
    assert len(json.dumps(d)) < 200_000
    c = d["cards"][0]
    for k in ("state", "equity", "ceiling_progress", "dd_room", "win_rate", "expectancy_r", "profit_factor", "sharpe", "verdict"): assert k in c


def test_metrics_verdict_needs_40_trades():
    t = [{"pnl": 1.0, "r": 1.0, "fee": 0, "slip_cost": 0, "entry_kind": "maker", "catchup": False}] * 39
    assert R.metrics(t, {"max_dd": 0.01, "_name": "x"}, [])["verdict"] == "dados insuficientes"
    assert R.metrics(t * 2, {"max_dd": 0.01, "_name": "x"}, [])["verdict"].startswith("possível GO")
