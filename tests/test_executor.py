"""Executor autónomo: TODOS os gates, stops do broker, target_balance, kill, reconciliação. Sem rede, sem conta real."""
import json, os, re, pathlib
import pytest
from desk import store
from desk.rules import Rules, load_rules
from live import executor as EX
from live.brokers import PaperBroker, LiveBroker, path_allowed

H, D = 3_600_000, 86_400_000
T0 = 1_800_000_000_000 // H * H
SYM = "TST-USD"


class FakeMarket:
    def __init__(self):
        self.tk = {SYM: {"bid": 99.9, "ask": 100.1, "mid": 100.0, "last_price": 100.0},
                   "BTC-USD": {"bid": 99.9, "ask": 100.1, "mid": 100.0, "last_price": 100.0}}   # sonda de dados (health)
        self.h1 = {SYM: []}; self.d1 = {SYM: []}; self.m1 = {SYM: []}

    def ticker(self, s): return dict(self.tk[s])
    def pairs(self): return {SYM: {"base_step": "0.0001", "quote_step": "0.01", "min_order_size": "0.0001", "min_order_size_quote": "1"}}

    def candles(self, s, interval, since, until=None):
        if interval == 1:
            return [c for c in self.m1.get(s, []) if c["start"] >= since // 60_000 * 60_000 and (until is None or c["start"] < until)]
        src = self.h1 if interval == 60 else self.d1
        return [c for c in src.get(s, []) if c["start"] >= (since // H * H)]

    def bar(self, start, o, h, l, c): self.h1[SYM].append({"start": start, "open": o, "high": h, "low": l, "close": c, "volume": 10})


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE", str(tmp_path))
    monkeypatch.setattr("desk.risk_officer.quarter_kelly", lambda c, r: None)
    m = FakeMarket(); clk = Clock(T0 + 600_000)
    b = PaperBroker(str(tmp_path / "px.json"), m, cash=1000.0, clock=clk)
    store.append("trade_plan.csv", [{"plan_id": "P1", "coin": SYM, "zone_id": "Z1", "entry": 100, "stop": 95, "tp_price": 120,
                                      "size": 1, "notional": 100, "risk_pct": 0.01, "add_number": 0, "anchor_low": 90, "created_ts": T0,
                                      "equity": 1000, "equity_source": "paper", "sizing_binding": "cap15"}])
    return {"m": m, "b": b, "clk": clk, "tmp": tmp_path}


def rules(**kw):
    # paper_fast desligado por defeito nos testes base (os testes do ensaio acelerado ligam-no explicitamente)
    return Rules({**load_rules().p, "execution_mode": "paper_autonomous", "paper_fast": False, "target_balance": 0, **kw})   # teto testado à parte


def run(e, t, r=None, envv=None, mode=None):
    e["clk"].t = t
    ex = EX.Executor(r or rules(), mode, e["b"], env=envv or {}, now=t, log=lambda *a: None)
    return ex, ex.run_once()


def test_default_mode_off_does_nothing(env):
    assert load_rules().p["execution_mode"] != "live"          # o ficheiro nunca é entregue em live
    ex = EX.Executor(rules(execution_mode="off"), None, env["b"], env={}, now=T0, log=lambda *a: None)
    assert ex.run_once() == {"ran": False, "why": "execution_mode=off"}
    assert env["b"].s["orders"] == {}


def test_full_cycle_entry_broker_stop_and_stop_exit(env):
    m, b = env["m"], env["b"]
    ex, res = run(env, T0 + 600_000)
    assert res["opened"] == ["P1"]
    o = next(iter(b.s["orders"].values()))
    assert o["type"] == "limit" and o["price"] == 99.9 and o["qty"] == pytest.approx(150 / 99.9, abs=1e-4)   # teto 15% de 1000
    m.bar(T0 + H, 100, 100.5, 99.5, 100)
    ex, res = run(env, T0 + 2 * H + 60_000)
    p = ex.st["positions"]["P1"]; assert p["status"] == "OPEN" and p["entry"] == 99.9
    tp = [x for x in b.s["orders"].values() if x["type"] == "tpsl"]
    assert len(tp) == 1 and tp[0]["sl"] == 95 and tp[0]["tp"] == pytest.approx(119.9) and tp[0]["qty"] == pytest.approx(1.5015)
    m.bar(T0 + 3 * H, 99, 99.5, 94, 94.5)
    ex, res = run(env, T0 + 4 * H + 60_000)
    p = ex.st["positions"]["P1"]; assert p["status"] == "CLOSED" and p["exit_rule"] == "STOP_BROKER" and p["r"] < -0.9
    assert b.s["bal"].get("TST", 0) == pytest.approx(0)
    kinds = [json.loads(l)["type"] for l in open(env["tmp"] / "outbox.jsonl")]
    assert {"EXEC_ENTRY_PLACED", "EXEC_ENTRY_FILLED", "EXEC_EXIT"} <= set(kinds)


def _open(env):
    env["m"].bar(T0 + H, 100, 100.5, 99.5, 100)
    run(env, T0 + 600_000); ex, _ = run(env, T0 + 2 * H + 60_000); return ex


def test_hard_stop_minus_8pct_when_plan_stop_is_wider(env):
    rows = store.read("trade_plan.csv"); rows[0]["stop"] = 80; rows[0]["tp_price"] = 180; store.write("trade_plan.csv", rows)
    ex = _open(env); p = ex.st["positions"]["P1"]
    assert p["stop"] == pytest.approx(99.9 * 0.92)


def test_take_profit_and_same_bar_prefers_stop(env):
    ex = _open(env)
    env["m"].bar(T0 + 3 * H, 100, 125, 94, 110)            # stop e TP na mesma vela → stop (conservador)
    ex, _ = run(env, T0 + 4 * H + 60_000)
    assert ex.st["positions"]["P1"]["exit_rule"] == "STOP_BROKER"


def test_tp_exit(env):
    ex = _open(env)
    env["m"].bar(T0 + 3 * H, 100, 121, 99.5, 120)
    ex, _ = run(env, T0 + 4 * H + 60_000)
    p = ex.st["positions"]["P1"]; assert p["exit_rule"] == "TAKE_PROFIT_BROKER" and p["r"] == pytest.approx((119.9 - 99.9) / 4.9)


def test_breakeven_cancel_replace_with_new_idempotent_id(env):
    ex = _open(env)
    env["m"].bar(T0 + 3 * H, 100, 105.5, 99.8, 105)         # ≥ entry + 1R → BE
    ex, _ = run(env, T0 + 4 * H + 60_000)
    p = ex.st["positions"]["P1"]; assert p["at_be"] and p["stop"] == pytest.approx(99.9)
    tps = [x for x in env["b"].s["orders"].values() if x["type"] == "tpsl"]
    assert [x["status"] for x in tps] == ["cancelled", "new"] and tps[1]["sl"] == pytest.approx(99.9)
    assert tps[1]["coid"] == EX.coid("paper_autonomous", "P1", "tpsl", 2) != tps[0]["coid"]


def test_kill_cancels_entries_keeps_broker_stops(env):
    run(env, T0 + 600_000)
    open(store.path("KILL"), "w").write("x")
    ex, res = run(env, T0 + 700_000)
    assert res["killed"] and ex.st["positions"]["P1"]["status"] == "CANCELLED"
    assert all(o["status"] == "cancelled" for o in env["b"].s["orders"].values())
    os.remove(store.path("KILL"))


def test_kill_flatten(env):
    ex = _open(env); open(store.path("KILL"), "w").write("x")
    ex, res = run(env, T0 + 2 * H + 120_000, rules(exec_kill_action="flatten"))
    p = ex.st["positions"]["P1"]; assert p["status"] == "CLOSED" and p["exit_rule"] == "KILL_SWITCH"
    assert env["b"].s["bal"].get("TST", 0) == pytest.approx(0)
    os.remove(store.path("KILL"))


def test_target_balance_latched_until_manual_rebase(env):
    ex, res = run(env, T0 + 600_000, envv={"BOT_TARGET_BALANCE": "900"})
    assert res["opened"] == [] and any(r.startswith("TARGET_BALANCE") for r in res["gates"]["reasons"])
    assert any(n["type"] == "EXEC_TARGET_REACHED" for n in res["notes"])
    env["b"].s["bal"]["USD"] = 500.0                      # utilizador levantou 500
    store.append("trade_plan.csv", [{"plan_id": "P2", "coin": SYM, "zone_id": "Z2", "entry": 100, "stop": 95, "tp_price": 120,
                                      "risk_pct": 0.01, "add_number": 0, "anchor_low": 90, "created_ts": T0 + H}])
    ex, res = run(env, T0 + H + 600_000, envv={"BOT_TARGET_BALANCE": "900"})
    assert any(n["type"] == "EXEC_REBASED" for n in res["notes"]) and res["gates"]["dd"] == 0
    assert res["opened"] == [] and ex.st["target_latched"]          # NÃO retoma sozinho: só rebase manual

def test_dd_reduce_and_suspend_latched(env):
    # o critério de morte (DD > 20% → KILL) dispara antes do SUSPEND 30%; aqui desliga-se só para testar o trinco legado
    R30 = rules(kill_dd_max=0.99)
    ex, _ = run(env, T0 + 600_000)
    ex.cancel_pending("t"); ex.save()
    env["b"].s["bal"]["USD"] = 840.0                       # −16%
    store.append("trade_plan.csv", [{"plan_id": "P3", "coin": SYM, "zone_id": "Z3", "entry": 100, "stop": 95, "tp_price": 120,
                                      "risk_pct": 0.01, "add_number": 0, "anchor_low": 90, "created_ts": T0 + D}])
    ex, res = run(env, T0 + D + 600_000)
    assert res["gates"]["risk_mult"] == 0.5 and ex.st["positions"]["P3"]["risk"] == pytest.approx(0.005)
    ex.cancel_pending("t"); ex.save()
    env["b"].s["bal"]["USD"] = 690.0                       # −31%
    ex, res = run(env, T0 + 2 * D + 600_000, R30)
    assert ex.st["suspended"] and res["gates"]["block_entries"]
    env["b"].s["bal"]["USD"] = 1000.0                      # recupera, mas SUSPEND fica trancado
    ex, res = run(env, T0 + 3 * D + 600_000, R30)
    assert any(r.startswith("DD_SUSPEND") for r in res["gates"]["reasons"])


def test_daily_loss_halt(env):
    ex, _ = run(env, T0 + 600_000); ex.cancel_pending("t"); ex.save()
    env["b"].s["bal"]["USD"] = 960.0                       # −4% no mesmo dia
    store.append("trade_plan.csv", [{"plan_id": "P4", "coin": SYM, "zone_id": "Z4", "entry": 100, "stop": 95, "tp_price": 120,
                                      "risk_pct": 0.01, "add_number": 0, "anchor_low": 90, "created_ts": T0}])
    ex, res = run(env, T0 + 900_000)
    assert any(r.startswith("DAILY_LOSS_HALT") for r in res["gates"]["reasons"]) and res["opened"] == []


def test_max_positions_and_order_cap(env):
    plans = [{"plan_id": f"Q{i}", "coin": SYM, "zone_id": f"ZQ{i}", "entry": 100, "stop": 95, "tp_price": 120, "risk_pct": 0.01,
              "add_number": 0, "anchor_low": 90, "created_ts": T0} for i in range(7)]
    store.append("trade_plan.csv", plans); env["b"].s["bal"]["USD"] = 100000.0
    ex, res = run(env, T0 + 600_000)
    assert len(res["opened"]) == 5
    ex2 = EX.Executor(rules(exec_max_orders_day=0), None, env["b"], env={}, now=T0 + 700_000, log=lambda *a: None)
    assert "ORDER_CAP" in ex2.run_once()["gates"]["reasons"]


def test_old_plans_never_executed(env):
    ex = EX.Executor(rules(), None, env["b"], env={}, now=T0 + 3 * H, log=lambda *a: None)
    ex.st["enabled_ts"] = T0 + 3 * H
    assert ex.run_once()["opened"] == []


def test_external_close_reconciled(env):
    ex = _open(env)
    env["b"].s["bal"]["TST"] = 0.0                         # vendido na app pelo utilizador
    ex, _ = run(env, T0 + 2 * H + 120_000)
    p = ex.st["positions"]["P1"]; assert p["exit_rule"] == "EXTERNAL_CLOSE"
    assert all(o["status"] != "new" for o in env["b"].s["orders"].values() if o["type"] == "tpsl")


def test_unknown_placement_outcome_adopted_by_client_order_id(env, monkeypatch):
    b = env["b"]; real = b.limit_buy

    def flaky(*a, **k):
        real(*a, **k); raise TimeoutError("read timeout")   # a ordem chegou, a resposta não
    monkeypatch.setattr(b, "limit_buy", flaky)
    ex, res = run(env, T0 + 600_000)
    assert ex.st["positions"]["P1"]["entry_oid"] is None
    monkeypatch.setattr(b, "limit_buy", real)
    ex, res = run(env, T0 + 700_000)
    assert ex.st["positions"]["P1"]["entry_oid"] == next(iter(b.s["orders"]))
    assert len(b.s["orders"]) == 1                          # sem duplicado


def test_partial_fill_at_ttl_protects_partial_qty(env):
    run(env, T0 + 600_000)
    o = next(iter(env["b"].s["orders"].values())); o["filled"], o["avg"], o["status"] = 0.5, 99.9, "partially_filled"
    env["b"].s["bal"]["TST"] = 0.5; env["b"].s["bal"]["USD"] -= 0.5 * 99.9; env["b"].save()
    ex, _ = run(env, T0 + 600_000 + 121 * 60_000)
    p = ex.st["positions"]["P1"]; assert p["status"] == "OPEN" and p["qty"] == pytest.approx(0.5)
    tp = [x for x in env["b"].s["orders"].values() if x["type"] == "tpsl"]; assert tp and tp[0]["qty"] == pytest.approx(0.5)


def test_stop_fallback_monitor_when_broker_rejects(env, monkeypatch):
    env["m"].bar(T0 + H, 100, 100.5, 99.5, 100); run(env, T0 + 600_000)
    monkeypatch.setattr(env["b"], "tpsl_sell", lambda *a, **k: {"id": None, "status": "rejected"})
    ex, res = run(env, T0 + 2 * H + 60_000)
    p = ex.st["positions"]["P1"]; assert p["stop_mode"] == "monitor"
    assert any(n["type"] == "EXEC_STOP_FALLBACK" for n in res["notes"])
    env["m"].tk[SYM].update(bid=94.0, ask=94.2, mid=94.1)
    ex, _ = run(env, T0 + 2 * H + 120_000)
    assert ex.st["positions"]["P1"]["exit_rule"] == "STOP_MONITOR"


def _go_report(tmp, day, verdict="GO"):
    d = tmp / "reports"; d.mkdir(exist_ok=True); (d / f"weekly_{day}.md").write_text(f"Veredito: {verdict} (x).\n")


LIVE_ENV = {"BOT_LIVE_CONFIRM": "EU ACEITO ORDENS REAIS NA REVOLUT X", "BOT_KEY_ATTESTED": "trade_only_no_withdraw", "BOT_TARGET_BALANCE": "5000"}


@pytest.mark.parametrize("drop,expect", [("BOT_LIVE_CONFIRM", "BOT_LIVE_CONFIRM"), ("BOT_KEY_ATTESTED", "BOT_KEY_ATTESTED"),
                                         ("BOT_TARGET_BALANCE", "target_balance")])
def test_live_gates_env(env, monkeypatch, drop, expect):
    monkeypatch.setattr("desk.auditor.stats", lambda r: {"go": True})
    _go_report(env["tmp"], EX.day_of(T0))
    e = {k: v for k, v in LIVE_ENV.items() if k != drop}
    ex, res = run(env, T0 + 600_000, rules(execution_mode="live"), e)
    assert any(expect in f for f in res["blocked"]) and env["b"].s["orders"] == {}


def test_live_gate_auditor(env, monkeypatch):
    monkeypatch.setattr("desk.auditor.stats", lambda r: {"go": True})
    r = rules(execution_mode="live")
    ex, res = run(env, T0 + 600_000, r, LIVE_ENV); assert any("AUDITOR_NOT_GO" in f for f in res["blocked"])   # sem relatório
    _go_report(env["tmp"], EX.day_of(T0 - 10 * D))
    ex, res = run(env, T0 + 600_000, r, LIVE_ENV); assert any("antigo" in f for f in res["blocked"])
    _go_report(env["tmp"], EX.day_of(T0), "NO-GO")
    ex, res = run(env, T0 + 600_000, r, LIVE_ENV); assert any("NO-GO" in f for f in res["blocked"])
    _go_report(env["tmp"], EX.day_of(T0), "GO")
    monkeypatch.setattr("desk.auditor.stats", lambda r: {"go": False})
    ex, res = run(env, T0 + 600_000, r, LIVE_ENV); assert any("stats actuais" in f for f in res["blocked"])
    assert env["b"].s["orders"] == {}
    monkeypatch.setattr("desk.auditor.stats", lambda r: {"go": True})
    ex, res = run(env, T0 + 600_000, r, LIVE_ENV); assert res["opened"] == ["P1"]   # todos os gates passam → ordem


class FakeResp:
    def __init__(self, code=200, body=None): self.status_code, self._b, self.headers = code, body, {}
    @property
    def content(self): return b"" if self._b is None else b"x"
    def json(self): return self._b
    text = ""


class FakeSession:
    def __init__(self): self.calls = []
    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append((method, url, json.loads(data) if data else None))
        if method == "POST": return FakeResp(200, {"data": {"venue_order_id": "7a52e92e-8639-4fe1-abaa-68d3a2d5234b", "client_order_id": "c", "state": "new"}})
        if method == "DELETE": return FakeResp(204)
        return FakeResp(200, [])


def _live():
    from bot.revolutx import RevolutXClient
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    s = FakeSession(); c = RevolutXClient("k" * 64, Ed25519PrivateKey.generate(), session=s, sleep=lambda x: None)
    return LiveBroker(c), s


def test_live_broker_tpsl_body_and_whitelist():
    b, s = _live()
    b.tpsl_sell("BTC-USD", "0.001", "110000", "90000", "3fa85f64-5717-4562-b3fc-2c963f66afa6")
    m, url, body = s.calls[-1]
    assert m == "POST" and url.endswith("/api/1.0/orders")
    assert body["order_configuration"] == {"tpsl": {"base_size": "0.001", "take_profit": {"trigger_price": "110000", "limit_price": "110000"},
                                                    "stop_loss": {"trigger_price": "90000"}}} and body["side"] == "sell"
    with pytest.raises(PermissionError): b.c.cancel_all()                       # cancel-all bloqueado
    with pytest.raises(PermissionError): b.c._request("POST", "/withdrawals", body={})
    with pytest.raises(PermissionError): b.c._request("POST", "/transfers", body={})
    b.cancel("7a52e92e-8639-4fe1-abaa-68d3a2d5234b"); assert s.calls[-1][0] == "DELETE"
    assert EX.structural_safety_check(b)[0]
    assert not path_allowed("GET", "/api/1.0/withdraw/history") and path_allowed("GET", "/api/1.0/balances")


def test_no_transfer_or_withdraw_code_anywhere():
    src = "\n".join(p.read_text() for d in ("live", "bot/revolutx", "bot/brokers", "desk") for p in pathlib.Path(d).glob("*.py"))
    assert not re.search(r"def\s+\w*(withdraw|transfer|deposit)\w*\s*\(", src, re.I)
    assert not re.search(r"[\"']/(api/\d\.\d/)?(withdraw|transfer|deposit)", src, re.I)
    # desk/ continua sem nenhuma chamada de ordem
    d = "\n".join(p.read_text() for p in pathlib.Path("desk").glob("*.py"))
    assert not re.search(r"place_order|place_tpsl|cancel_order|cancel_all", d)


def test_rules_validation_execution_mode():
    from desk.rules import parse_params
    with pytest.raises(ValueError):
        txt = re.sub(r"execution_mode: \w+", "execution_mode: yolo", open("desk/DESK_RULES.md").read())
        import desk.rules as R, tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False); f.write(txt); f.close(); R.load_rules(f.name)


def test_gate_text_autonomous_is_notification(env, monkeypatch):
    from desk import gate
    monkeypatch.setattr("desk.market.candles", lambda *a, **k: [])
    monkeypatch.setattr("desk.roles.guard.check", lambda *a, **k: {"ok": True, "reasons": []})
    gate.run(rules(), T0, None, lambda *a: None)
    a = [json.loads(l) for l in open(env["tmp"] / "outbox.jsonl") if "ENTRY_ALERT" in l][0]
    assert a["reply_options"] == [] and "não é preciso TAKEN/SKIPPED" in a["text"]


# ---------------- teto 1000 / reset 65 / critérios de morte (desk/health.py) ----------------
from desk import health as HL


def test_desk_rules_ceiling_1000_reset_65_and_kill_params():
    p = load_rules().p
    assert p["target_balance"] == 1000 and p["reset_balance"] == 65 and p["kill_dd_max"] == 0.20
    assert HL.ceiling(load_rules(), env={}) == 1000 and HL.reset_balance(load_rules()) == 65
    assert p["execution_mode"] != "live"


def test_ceiling_1000_does_not_enable_live(env, monkeypatch):
    monkeypatch.setattr("desk.auditor.stats", lambda r: {"go": True})
    ex, res = run(env, T0 + 600_000, rules(execution_mode="live", target_balance=1000), {})
    assert any("BOT_LIVE_CONFIRM" in f for f in res["blocked"]) and any("BOT_KEY_ATTESTED" in f for f in res["blocked"])
    assert any("AUDITOR_NOT_GO" in f for f in res["blocked"]) and not any("target_balance" in f for f in res["blocked"])
    assert env["b"].s["orders"] == {}
    with pytest.raises(SystemExit):                       # live sem chave de trading → nem constrói broker
        EX.make_broker("live", rules(execution_mode="live", target_balance=1000), env={})


def test_ceiling_pauses_notifies_and_paper_rebase_resets_to_65(env, monkeypatch):
    r = rules(target_balance=1000, reset_balance=65)
    ex, res = run(env, T0 + 600_000, r)                    # cash 1000 ≥ teto 1000
    assert res["opened"] == [] and ex.st["target_latched"]["target"] == 1000
    n = [x for x in res["notes"] if x["type"] == "EXEC_TARGET_REACHED"][0]
    assert "teto atingido, sacar e deixar o saldo inicial" in n["text"] and "SIMULADO" in n["text"] and "$65" in n["text"]
    env["b"].s["bal"]["USD"] = 990.0; env["b"].save()
    ex, res = run(env, T0 + 700_000, r); assert res["opened"] == [] and ex.st["target_latched"]   # continua pausado
    # rebase manual (CLI `rebase --confirm`) em paper: saldo simulado → 65
    monkeypatch.setattr(EX, "state_dir", lambda mode: str(env["tmp"]))
    env["b"].save(); import shutil; shutil.copy(env["tmp"] / "px.json", env["tmp"] / "paper_exchange.json")
    before, reset = EX.paper_rebase(r, "paper_autonomous")
    assert before == 990.0 and reset == 65 and json.load(open(env["tmp"] / "paper_exchange.json"))["bal"] == {"USD": 65}


def test_paper_rebase_refused_with_open_position(env, monkeypatch):
    ex = _open(env); ex.save()
    monkeypatch.setattr(EX, "state_dir", lambda mode: str(env["tmp"] / "exec_paper_autonomous"))
    import shutil; shutil.copy(env["tmp"] / "px.json", env["tmp"] / "exec_paper_autonomous" / "paper_exchange.json")
    with pytest.raises(SystemExit): EX.paper_rebase(rules(), "paper_autonomous")


def test_forward_dd_over_20_auto_kills_and_stays_latched(env):
    ex, _ = run(env, T0 + 600_000); assert ex.st["positions"]["P1"]["status"] == "PENDING_ENTRY"
    env["b"].s["bal"]["USD"] = 780.0; env["b"].save()      # −22% (> 20%) com a entrada pendente
    ex, res = run(env, T0 + 700_000)
    assert res["killed"] and "forward_dd" in ex.st["kill_latched"]["reason"]
    assert ex.st["positions"]["P1"]["status"] == "CANCELLED"
    assert any(n["type"] == "EXEC_KILL_AUTO" and "SIMULADO" in n["text"] for n in res["notes"])
    env["b"].s["bal"]["USD"] = 1000.0
    ex, res = run(env, T0 + 800_000); assert res["killed"]            # trancado até unkill --confirm
    ex.st["kill_latched"] = None; ex.save()
    ex, res = run(env, T0 + 900_000); assert not res.get("killed")


def test_dd_15_is_not_a_kill(env):
    run(env, T0 + 600_000); env["b"].s["bal"]["USD"] = 850.0; env["b"].save()
    ex, res = run(env, T0 + 700_000); assert not res.get("killed") and ex.st["kill_metrics"]["criteria"]["forward_dd"]["value"] == "15.00%"


def test_api_outage_3h_does_not_kill_but_24h_does(env, monkeypatch):
    monkeypatch.setattr(EX, "state_dir", lambda mode: str(env["tmp"] / "exec"))
    r = rules()
    record = EX.record_health("paper_autonomous", T0, True)
    for k in range(1, 5):                                  # 10h, 11h, 12h, 13h a falhar (o 502 de 2026-10-20)
        out = EX.on_run_failure(r, "paper_autonomous", T0 + k * H, "HTTPError: 502", log=lambda *a: None)
    assert "kill_latched" not in out and out["fail_streak"] == 4
    EX.record_health("paper_autonomous", T0 + 5 * H, True)           # voltou
    for k in range(6, 6 + 26):
        out = EX.on_run_failure(r, "paper_autonomous", T0 + k * H, "HTTPError: 502", log=lambda *a: None)
    assert out["kill_latched"] and "api_errors" in out["kill_latched"]["reason"]
    ob = [json.loads(l) for l in open(env["tmp"] / "outbox.jsonl")]
    assert any(a["type"] == "EXEC_KILL_AUTO" for a in ob)


def test_data_stale_over_3_days_kills():
    p = HL.params({}); h = {}
    HL.record_run(h, T0, True)
    assert not HL.stale_eval(h["last_data_ok_ts"], h["first_ts"], T0 + 3 * D, p)["tripped"]
    assert HL.stale_eval(h["last_data_ok_ts"], h["first_ts"], T0 + 3 * D + H, p)["tripped"]


def test_api_error_rate_criterion():
    p = HL.params({}); h = {}
    for k in range(40): HL.record_run(h, T0 + k * H, k % 2 == 0)      # 50% a falhar alternado (streak nunca chega a 24 h)
    e = HL.api_eval(h, T0 + 40 * H, p); assert e["tripped"] and e["why"] == "API_ERROR_RATE"


def test_sharpe_and_divergence_insufficient_until_history():
    p = HL.params({})
    assert not HL.sharpe_eval([65.0] * 30, p)["measurable"]
    down = [100 * (0.999 ** i) * (1 + 0.001 * ((-1) ** i)) for i in range(400)]
    s = HL.sharpe_eval(down, p); assert s["measurable"] and s["tripped"]
    r = rules()
    assert not HL.executor_diverge_eval(r, [(T0, 65.0)], T0 + 5 * D, p)["measurable"]


def test_executor_divergence_vs_desk_journal(env):
    p = HL.params({}); r = rules(paper_equity=10000)
    store.append("journal.csv", [{"ts": store.iso(T0 + 10 * D), "trade_id": "X", "coin": SYM, "line": "ENTRY", "amount_usd": -1000, "mode": "PAPER"},
                                 {"ts": store.iso(T0 + 11 * D), "trade_id": "X", "coin": SYM, "line": "EXIT", "amount_usd": 1100, "mode": "PAPER"}])
    rows = [(T0, 65.0), (T0 + 31 * D, 65.0)]                     # executor parado; desk +1% → 1 pp (ok)
    e = HL.executor_diverge_eval(r, rows, T0 + 31 * D, p); assert e["measurable"] and not e["tripped"]
    rows = [(T0, 65.0), (T0 + 31 * D, 62.4)]                     # executor −4% vs desk +1% → 5 pp
    assert HL.executor_diverge_eval(r, rows, T0 + 31 * D, p)["tripped"]
