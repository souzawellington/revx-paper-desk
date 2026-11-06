"""GUARD (Texto 2): vetos duros ANTES do Gate. Nunca envia ordens.
- max_open_positions
- max_total_risk_pct (risco agregado de OPEN paper+TAKEN + planos pendentes)
- daily loss halt (PnL paper do dia UTC)
- ficheiro KILL (Texto 4): bloqueia tudo
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from ..rules import load_rules, eff, paper_fast_active
from .. import store, logic as L
from ..positions import decision_for


def kill_path() -> str:
    return store.path("KILL")


def is_killed() -> bool:
    return os.path.exists(kill_path())


def paper_day_pnl(rules, now_ms: int | None = None) -> float:
    """Soma RESULT paper com ts no dia UTC corrente."""
    now_ms = now_ms or store.now_ms()
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    pnl = 0.0
    for r in store.read("journal.csv"):
        if r.get("line") != "RESULT" or r.get("mode") != "PAPER": continue
        if (r.get("ts") or "")[:10] != day: continue
        pnl += store.f(r.get("amount_usd"), 0.0)
    return pnl


def open_risk_frac(rules, now_ms: int | None = None) -> tuple[int, float]:
    """(n_open, risco_fracção_agregada) — posições OPEN + planos AINDA À ESPERA do fill (slot reservado).
    Correcção (2026-10-20): antes, qualquer plano do trade_plan.csv cuja posição não estivesse OPEN contava como slot
    reservado — também os já CLOSED/VOID (fantasmas), o que travava o desk em MAX_OPEN_POSITIONS para sempre.
    Agora só conta: posições OPEN (não SKIPPED) + planos sem NENHUMA linha em positions.csv, não SKIPPED e recentes
    (≤ max_alert_age_hours + 1h; o auditor preenche-os na abertura 1H seguinte, por isso mais antigos não são reservas)."""
    now_ms = now_ms or store.now_ms()
    rows = store.read("positions.csv")
    skipped = {d["plan_id"] for d in store.read("decisions.csv") if d.get("decision") == "SKIPPED"}
    pos = [p for p in rows if p.get("status") == "OPEN" and p.get("plan_id") not in skipped]
    known = {p.get("plan_id") for p in rows}
    n = len(pos)
    risk = sum(store.f(p.get("risk_pct"), 0.0) for p in pos)
    horizon = (float(rules.max_alert_age_hours) + 1) * L.H
    for pl in store.read("trade_plan.csv"):
        if pl["plan_id"] in known or pl["plan_id"] in skipped: continue
        created = store.f(pl.get("created_ts"), 0.0) or 0.0
        if now_ms - created > horizon: continue      # plano antigo nunca preenchido: não reserva slot
        risk += store.f(pl.get("risk_pct"), 0.0)
        n += 1  # conta como slot reservado
    return n, risk


def check(rules=None, now=None, log=print) -> dict:
    """Devolve {ok, reasons, killed, n_open, total_risk, day_pnl}."""
    rules = rules or load_rules(); now = now or store.now_ms()
    reasons = []
    killed = is_killed()
    if killed:
        reasons.append("KILL_SWITCH")
    n_open, total_risk = open_risk_frac(rules, now)
    max_open, max_risk = int(eff(rules, "max_open_positions")), float(eff(rules, "max_total_risk_pct"))
    if n_open >= max_open:
        reasons.append(f"MAX_OPEN_POSITIONS:{n_open}>={max_open}")
    if total_risk > max_risk + 1e-12:
        reasons.append(f"MAX_TOTAL_RISK:{total_risk:.4f}>{max_risk}")
    day_pnl = paper_day_pnl(rules, now)
    # equity paper approx
    from ..risk_officer import equity
    eq, _ = equity(rules, log=lambda *a: None)
    halt = -float(rules.daily_loss_halt_pct) * eq
    if day_pnl <= halt:
        reasons.append(f"DAILY_LOSS_HALT:pnl={day_pnl:.2f}<=halt={halt:.2f}")
    ok = not reasons
    out = {"ok": ok, "reasons": reasons, "killed": killed, "n_open": n_open, "max_open": max_open, "paper_fast": paper_fast_active(rules),
           "total_risk": total_risk, "day_pnl": day_pnl, "equity": eq}
    log(f"guard: {'PASS' if ok else 'VETO ' + ';'.join(reasons)} (open={n_open} risk={total_risk:.3%} day_pnl={day_pnl:.2f})")
    return out


def run(rules=None, now=None, log=print) -> dict:
    """Se veto: marca planos novos sem decisão como bloqueados (não emite Gate). Devolve check."""
    rules = rules or load_rules()
    st = check(rules, now, log)
    import json
    json.dump(st, open(store.path("guard_status.json"), "w"))   # sempre (antes só no veto → ficava um veto antigo)
    if st["ok"]:
        return st
    # regista veto; o Gate verifica guard antes de emitir
    store.append("plan_rejections.csv", [{"ts": store.iso(now or store.now_ms()), "coin": "*", "zone_id": "*",
                                          "reason": "GUARD_VETO:" + ";".join(st["reasons"])}])
    return st


def main():
    run()


if __name__ == "__main__":
    main()
