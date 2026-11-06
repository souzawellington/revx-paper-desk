"""Ensaio acelerado (paper_fast) + correcção dos «fantasmas» do GUARD. Sem rede, sem conta real."""
import csv, os, re
import pytest
from desk import store, auditor, gate, run as desk_run
from desk.rules import Rules, load_rules, eff, paper_fast_active, run_tag, PAPER_FAST_TAG
from desk.roles import guard
from live import executor as EX
from tests.test_desk import path_hours, FakeClient, T0 as DT0, H, D, desk_state  # noqa: F401
from tests.test_executor import env, run, SYM, T0  # noqa: F401


def R(**kw): return Rules({**load_rules().p, **kw})


def _pos(pid, status, **kw):
    return {"pid": pid, "plan_id": pid, "coin": f"{pid}-USD", "status": status, "entry": 1, "stop": 0.9, "initial_stop": 0.9,
            "tp_price": 1.4, "qty": 1, "risk_pct": 0.01, "add_number": 0, "anchor_low": 0.5, "opened_ts": 1, "peak": 1,
            "at_be": False, "stale_flagged": False, **kw}


def _plan(pid, created):
    return {"plan_id": pid, "coin": f"{pid}-USD", "zone_id": pid, "entry": 1, "stop": 0.9, "tp_price": 1.4, "size": 1,
            "notional": 1, "risk_pct": 0.01, "add_number": 0, "anchor_low": 0.5, "created_ts": created}


# ---------------- (a) fantasmas ----------------
def test_guard_ghosts_closed_void_skipped_and_stale_plans_not_counted(desk_state):
    now = store.now_ms(); r = R(execution_mode="off")
    # cenário real de 2026-10-20: 4 planos CLOSED + 1 OPEN → antes contava 5 (5>=5 veto)
    store.write("positions.csv", [_pos("A", "CLOSED"), _pos("B", "CLOSED"), _pos("C", "CLOSED"), _pos("D", "CLOSED"),
                                  _pos("E", "OPEN"), _pos("V", "VOID")])
    store.append("trade_plan.csv", [_plan(x, now - 30 * H) for x in "ABCDEV"])
    n, risk = guard.open_risk_frac(r, now)
    assert n == 1 and risk == pytest.approx(0.01)
    assert guard.check(r, now, log=lambda *a: None)["ok"]
    # plano novo à espera do fill (recente) reserva slot; plano antigo nunca preenchido não
    store.append("trade_plan.csv", [_plan("NEW", now - H // 2), _plan("OLD", now - 10 * H)])
    assert guard.open_risk_frac(r, now)[0] == 2
    # SKIPPED (hipotético) não ocupa slot, nem como posição OPEN nem como plano pendente
    store.append("decisions.csv", [{"ts": "x", "alert_id": "ENTRY:E", "plan_id": "E", "decision": "SKIPPED"},
                                   {"ts": "x", "alert_id": "ENTRY:NEW", "plan_id": "NEW", "decision": "SKIPPED"}])
    assert guard.open_risk_frac(r, now) == (0, 0.0)


def test_guard_still_vetoes_real_open_positions(desk_state):
    store.write("positions.csv", [_pos(f"P{i}", "OPEN") for i in range(5)])
    st = guard.check(R(execution_mode="off"), log=lambda *a: None)
    assert not st["ok"] and "MAX_OPEN_POSITIONS:5>=5" in st["reasons"]
    guard.run(R(execution_mode="off"), log=lambda *a: None)
    store.write("positions.csv", [])
    guard.run(R(execution_mode="off"), log=lambda *a: None)       # guard_status.json reflecte o estado actual
    import json; assert json.load(open(store.path("guard_status.json")))["ok"]


# ---------------- paper_fast só em paper_autonomous ----------------
@pytest.mark.parametrize("mode,active", [("off", False), ("live", False), ("paper_autonomous", True)])
def test_paper_fast_only_in_paper_autonomous(mode, active):
    r = R(execution_mode=mode, paper_fast=True)
    assert paper_fast_active(r) is active
    assert eff(r, "max_open_positions") == (10 if active else 5)
    assert eff(r, "max_total_risk_pct") == (0.10 if active else 0.05)
    assert run_tag(r) == (PAPER_FAST_TAG if active else "")
    assert eff(R(execution_mode=mode, paper_fast=False), "max_open_positions") == 5


def test_guard_paper_fast_allows_more_positions(desk_state):
    store.write("positions.csv", [_pos(f"P{i}", "OPEN") for i in range(7)])
    assert guard.check(R(execution_mode="paper_autonomous", paper_fast=True), log=lambda *a: None)["ok"]
    assert not guard.check(R(execution_mode="live", paper_fast=True), log=lambda *a: None)["ok"]
    store.write("positions.csv", [_pos(f"P{i}", "OPEN") for i in range(10)])
    assert not guard.check(R(execution_mode="paper_autonomous", paper_fast=True), log=lambda *a: None)["ok"]


def test_rules_paper_fast_hard_limits(tmp_path):
    base = open("desk/DESK_RULES.md").read()
    for old, new in [("paper_max_open_positions: 10", "paper_max_open_positions: 11"),
                     ("paper_max_total_risk_pct: 0.10", "paper_max_total_risk_pct: 0.2"),
                     ("paper_entry_tol: 0.01", "paper_entry_tol: 0.05"),
                     ("paper_entry_mode: marketable", "paper_entry_mode: yolo"),
                     ("paper_fast: true", "paper_fast: true\npaper_risk_pct: 0.02"),
                     ("risk_pct: 0.01", "risk_pct: 0.02")]:
        txt, k = re.subn("^" + re.escape(old), lambda m: new, base, count=1, flags=re.M)   # só a linha do bloco params
        assert k == 1
        p = tmp_path / "R.md"; p.write_text(txt)
        with pytest.raises(ValueError): load_rules(str(p))
    r = load_rules()
    # parâmetros de risco e limiares congelados intocados
    assert (r.risk_pct, r.max_position_frac, r.hard_stop_pct, r.daily_loss_halt_pct, r.max_open_positions) == (0.01, 0.15, 0.08, 0.03, 5)
    assert (r.threshold_trades, r.threshold_win_rate, r.threshold_expectancy_r, r.threshold_max_dd) == (40, 0.33, 0.4, 0.20)
    assert r.p["exec_dd_reduce"] == 0.15 and r.p["exec_dd_suspend"] == 0.30 and r.p["execution_mode"] != "live"


# ---------------- executor ----------------
def fast(**kw):
    return Rules({**load_rules().p, "execution_mode": "paper_autonomous", "paper_fast": True, "target_balance": 0, **kw})   # teto testado à parte


def _plans(n):
    # stop a −20% → notional 5% por posição, para o cash (sem alavancagem) não ser o limite do teste
    return [{"plan_id": f"Q{i}", "coin": SYM, "zone_id": f"ZQ{i}", "entry": 100, "stop": 80, "tp_price": 180, "risk_pct": 0.01,
             "add_number": 0, "anchor_low": 90, "created_ts": T0} for i in range(n)]


def test_executor_paper_fast_more_slots_marketable_fill_and_tag(env):
    store.append("trade_plan.csv", _plans(11)); env["b"].s["bal"]["USD"] = 100000.0
    ex, res = run(env, T0 + 600_000, fast())
    assert len(res["opened"]) == 10                                     # P1 + Q0..Q8 (limite paper 10)
    st = ex.st["positions"]
    assert all(p["status"] == "OPEN" and p["tag"] == PAPER_FAST_TAG for p in st.values())
    p = st["P1"]; assert p["entry"] == pytest.approx(100.1 * 1.001)    # ask + slippage (taker), não post-only
    assert p["stop"] == 95 and p["risk"] == 0.01                         # stop e risco do plano inalterados
    o = env["b"].s["orders"][p["entry_oid"]]; assert o["status"] == "filled"
    assert any(x["type"] == "tpsl" for x in env["b"].s["orders"].values())   # stop do broker colocado logo
    rows = list(csv.DictReader(open(os.path.join(ex.dir, "exec_journal.csv"))))
    assert rows and all(r["tag"] == PAPER_FAST_TAG for r in rows) and rows[0]["event"] == "ENTRY"
    assert any("marketable" in n["text"] and PAPER_FAST_TAG in n["text"] for n in res["notes"])


def test_executor_paper_fast_falls_back_to_post_only_when_price_ran(env):
    env["m"].tk[SYM] = {"bid": 101.9, "ask": 102.1, "mid": 102.0, "last_price": 102.0}   # ask > 100 × 1.01
    ex, res = run(env, T0 + 600_000, fast())
    p = ex.st["positions"]["P1"]
    assert p["status"] == "PENDING_ENTRY" and p["limit"] == pytest.approx(100.2)
    assert env["b"].s["orders"][p["entry_oid"]]["status"] == "new"


def test_executor_paper_fast_never_in_live_or_off(env):
    r = fast()
    ex = EX.Executor(r, "live", env["b"], env={}, now=T0, log=lambda *a: None)
    assert not ex.fast() and ex.max_open() == 5
    ex2 = EX.Executor(Rules({**r.p, "execution_mode": "live"}), "paper_autonomous", env["b"], env={}, now=T0, log=lambda *a: None)
    assert not ex2.fast() and ex2.max_open() == 5                      # rules em live → ignorado
    ex3 = EX.Executor(r, "paper_autonomous", object(), env={}, now=T0, log=lambda *a: None)
    assert not ex3.fast()                                               # só com PaperBroker


def test_executor_base_still_five_and_post_only(env):
    store.append("trade_plan.csv", _plans(7)); env["b"].s["bal"]["USD"] = 100000.0
    ex, res = run(env, T0 + 600_000, fast(paper_fast=False))
    assert len(res["opened"]) == 5
    assert all(o["status"] == "new" for o in env["b"].s["orders"].values())
    assert all(p.get("tag", "") == "" for p in ex.st["positions"].values())


def test_executor_journal_migrates_old_header(env):
    ex = EX.Executor(fast(), None, env["b"], env={}, now=T0, log=lambda *a: None)
    os.makedirs(ex.dir, exist_ok=True); p = os.path.join(ex.dir, "exec_journal.csv")
    open(p, "w").write("ts,mode,pid,symbol,event,qty,price,r,note\n2026,paper_autonomous,X,TST-USD,ENTRY,1,1,,\n")
    ex.journal({"pid": "Y", "symbol": SYM, "event": "EXIT", "qty": 1, "price": 2, "tag": PAPER_FAST_TAG})
    rows = list(csv.DictReader(open(p)))
    assert [r["tag"] for r in rows] == ["", PAPER_FAST_TAG] and rows[0]["pid"] == "X"


# ---------------- desk + auditor: tag até ao relatório ----------------
def _pipeline(rules):
    h1 = path_hours(); cli = FakeClient(h1)
    desk_run.stage("daily", rules, cli, now=DT0 + 63 * D, log=lambda *a: None)
    w = store.read("watchlist.csv")
    for row in w: row["tag"] = "PRIME"
    store.write("watchlist.csv", w)
    desk_run.stage("1h", rules, cli, now=DT0 + 63 * D + 13 * H, log=lambda *a: None)
    desk_run.stage("1h", rules, cli, now=DT0 + 63 * D + 14 * H, log=lambda *a: None)
    t_end = DT0 + len(h1) * H
    desk_run.stage("4h", rules, cli, now=t_end, log=lambda *a: None)
    desk_run.stage("weekly", rules, cli, now=t_end, log=lambda *a: None)
    return [a for a in store.outbox() if a["type"] == "WEEKLY_REPORT"][0]


def test_desk_pipeline_tags_paper_fast_through_journal_and_weekly(desk_state):
    rep = _pipeline(R(execution_mode="paper_autonomous", paper_fast=True))
    assert store.read("trade_plan.csv")[0]["tag"] == PAPER_FAST_TAG
    assert store.read("positions.csv")[0]["tag"] == PAPER_FAST_TAG
    res = [j for j in store.read("journal.csv") if j["line"] == "RESULT"]
    assert res and all(j["tag"] == PAPER_FAST_TAG for j in res)
    r = load_rules()
    assert auditor.stats(r, tag=PAPER_FAST_TAG)["n"] == len(res) and auditor.stats(r, tag="")["n"] == 0
    assert auditor.stats(r)["n"] == len(res)                                  # o GO conta todos
    assert "Ensaio acelerado (paper_fast" in rep["text"] and rep["data"]["n_paper_fast"] == len(res)


def test_desk_pipeline_no_tag_when_off(desk_state):
    _pipeline(R(execution_mode="off"))
    assert store.read("trade_plan.csv")[0]["tag"] == ""
    assert all(j["tag"] == "" for j in store.read("journal.csv"))
