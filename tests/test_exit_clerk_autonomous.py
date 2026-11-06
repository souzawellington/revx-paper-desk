"""exit_clerk em paper_autonomous: alertas só para posições que o executor (Bot D) segura; ledger/journal intactos."""
import json, os
from desk.rules import load_rules, Rules
from desk import store, exit_clerk, auditor
from desk.roles import guard
from tests.test_desk import path_hours, FakeClient, T0, H, D, desk_state  # noqa: F401


def _pos(pid, coin="TST-USD"):
    return {"pid": pid, "plan_id": pid, "coin": coin, "status": "OPEN", "entry": 100, "stop": 99, "initial_stop": 99,
            "tp_price": 104, "qty": 1, "risk_pct": 0.01, "add_number": 0, "anchor_low": 90, "opened_ts": T0, "peak": 100,
            "at_be": False, "stale_flagged": False, "last_h1": "", "last_d1": "", "tag": "paper_fast"}


def _exec_state(positions):
    d = store.path("exec_paper_autonomous"); os.makedirs(d, exist_ok=True)
    json.dump({"positions": positions}, open(os.path.join(d, "state.json"), "w"))


def _rules(mode="paper_autonomous"):
    return Rules({**load_rules().p, "execution_mode": mode})


def test_executor_held_modes(desk_state):
    assert exit_clerk.executor_held(_rules("off")) is None
    assert exit_clerk.executor_held(_rules()) == set()            # sem state.json: o executor não segura nada
    _exec_state({"A": {"status": "OPEN"}, "B": {"status": "CLOSED"}, "C": {"status": "CANCELLED"}, "E": {"status": "PENDING_ENTRY"}})
    assert exit_clerk.executor_held(_rules()) == {"A"}
    open(store.path("exec_paper_autonomous/state.json"), "w").write("{corrupt")
    assert exit_clerk.executor_held(_rules()) is None              # ilegível → falha aberta (alerta como antes)


def test_kill_autonomous_no_alert_for_unheld_but_ledger_closed(desk_state):
    cli = FakeClient(path_hours())
    store.write("positions.csv", [_pos("P1"), _pos("P2")])
    _exec_state({"P1": {"status": "CLOSED"}, "P2": {"status": "OPEN"}})
    open(guard.kill_path(), "w").write("k")
    try:
        exit_clerk.run("4h", _rules(), now=T0 + 70 * D, client=cli, log=lambda *a: None)
    finally:
        os.remove(guard.kill_path())
    rows = store.read("positions.csv")
    assert all(r["status"] == "CLOSED" for r in rows)              # ledger do desk fecha os dois
    res = [j for j in store.read("journal.csv") if j["line"] == "RESULT"]
    assert {j["trade_id"] for j in res} == {"P1", "P2"}             # contagem do auditor intacta
    ob = [a for a in store.outbox() if a["type"] == "EXIT_NOW"]
    assert [a["pid"] for a in ob] == ["P2"] and "Bot D" in ob[0]["text"]
    internal = [json.loads(l) for l in open(store.path("exit_clerk_internal.jsonl"))]
    assert [x["pid"] for x in internal] == ["P1"] and internal[0]["why"] == "not_held_by_executor"


def test_stop_exit_autonomous_suppressed_unless_taken(desk_state):
    """Saída normal (velas): PENDING fora do executor → interno; TAKEN humano → alerta sempre."""
    cli = FakeClient(path_hours()); h = path_hours(); t_end = T0 + len(h) * H
    store.write("positions.csv", [_pos("P1"), _pos("P3")])
    store.append("decisions.csv", [{"ts": store.iso(T0), "alert_id": "ENTRY:P3", "plan_id": "P3", "decision": "TAKEN"}])
    _exec_state({})
    exit_clerk.run("4h", _rules(), now=t_end, client=cli, log=lambda *a: None)
    rows = {r["pid"]: r for r in store.read("positions.csv")}
    assert rows["P1"]["status"] == rows["P3"]["status"] == "CLOSED"
    assert [a["pid"] for a in store.outbox() if a["type"] in ("EXIT_NOW", "STALE")] == ["P3"]
    assert "Feche a posição" in store.outbox()[0]["text"]          # TAKEN: texto manual de sempre
    assert {j["trade_id"] for j in store.read("journal.csv") if j["line"] == "RESULT"} == {"P1", "P3"}


def test_off_mode_unchanged(desk_state):
    cli = FakeClient(path_hours())
    store.write("positions.csv", [_pos("P1")])
    open(guard.kill_path(), "w").write("k")
    try:
        exit_clerk.run("4h", _rules("off"), now=T0 + 70 * D, client=cli, log=lambda *a: None)
    finally:
        os.remove(guard.kill_path())
    assert [a["pid"] for a in store.outbox() if a["type"] == "EXIT_NOW"] == ["P1"]
    assert not os.path.exists(store.path("exit_clerk_internal.jsonl"))
