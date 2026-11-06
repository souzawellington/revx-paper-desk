"""Papel 5 — EXIT CLERK. Dono: posições abertas (paper + TAKEN; saldos read-only para verificação).
Em cada fecho 4H e diário verifica as regras de saída do DESK_RULES.md e emite EXIT NOW com a regra disparada.
Plano 72h -> STALE (o humano decide). Nunca discute uma regra; nunca sugere 'esperar mais uma vela'.
Em paper fecha a posição simulada (o Auditor regista no journal).

Modo autónomo (execution_mode == paper_autonomous): o ledger do desk (positions.csv) abre um fill paper para TODOS os
planos (auditor.paper_fill), mas o Bot D (live.executor) só segura alguns (entradas post-only podem expirar, stops do
broker saem antes). Nesse modo, alertas EXIT_NOW/STALE de posições PENDING (sem TAKEN/SKIPPED humano) que o executor
NÃO tem OPEN no seu state.json são internos: o ledger e o journal continuam a ser actualizados (contagem do auditor
intacta), mas o alerta não vai para o outbox — fica em exit_clerk_internal.jsonl. As saídas reais do Bot D chegam
como EXEC_EXIT do próprio executor."""
from __future__ import annotations
import argparse, json, os
from .rules import load_rules
from . import logic as L, market, store
from .positions import to_pos, update_row, decision_for
from . import auditor
from .roles import guard as guard_mod


AUTONOMOUS_MODES = ("paper_autonomous",)


def executor_held(rules):
    """pids que o executor autónomo tem OPEN; None = não filtrar (modo não autónomo ou estado ilegível → falha aberta)."""
    mode = str(rules.p.get("execution_mode", "off"))
    if mode not in AUTONOMOUS_MODES: return None
    sp = store.path(os.path.join(f"exec_{mode}", "state.json"))
    if not os.path.exists(sp): return set()
    try:
        st = json.load(open(sp))
        return {k for k, p in (st.get("positions") or {}).items() if (p or {}).get("status") == "OPEN"}
    except Exception:
        return None


def _internal(kind, r, rule, px, decision, why):
    with open(store.path("exit_clerk_internal.jsonl"), "a") as fh:
        fh.write(json.dumps({"ts": store.iso(store.now_ms()), "type": kind, "pid": r["pid"], "coin": r["coin"], "rule": rule,
                             "price": px, "decision": decision, "why": why}, default=str) + "\n")


def _alert(kind, r, rule, px, rules, decision, held=None):
    tag = "TAKEN" if decision == "TAKEN" else "PAPER"
    if tag == "PAPER" and not rules.p.get("alert_paper_exits", True): return
    if held is not None and decision == "PENDING" and r["pid"] not in held:
        _internal(kind, r, rule, px, decision, "not_held_by_executor"); return False
    auto = held is not None and decision == "PENDING"
    if kind == "EXIT_NOW":
        tp = store.f(r.get("tp_price"))
        text = (f"🔴 EXIT NOW [{tag}] {r['coin']} | regra: {rule} | preço {px:.6g} | entrada {float(r['entry']):.6g} | "
                f"stop {float(r['stop']):.6g} | TP {tp if tp else '—'} | âncora {float(r['anchor_low']):.6g}\n"
                + ("Informativo: o Bot D (paper_autonomous) gere esta saída sozinho — nada a fazer." if auto
                   else "Feche a posição (o desk não executa)."))
        aid = f"EXIT:{r['pid']}:{rule}"
    else:
        text = (f"🟡 STALE [{tag}] {r['coin']} | posição plana há ≥{rules.stale_hours}h (|Δ| < {rules.stale_band:.1%}) | "
                f"entrada {float(r['entry']):.6g} | preço {px:.6g}\n"
                + ("Informativo: o Bot D (paper_autonomous) gere esta posição sozinho." if auto else "Decisão humana: manter ou fechar."))
        aid = f"STALE:{r['pid']}"
    store.emit({"id": aid, "type": kind, "coin": r["coin"], "pid": r["pid"], "plan_id": r["plan_id"], "rule": rule,
                "text": text, "chart_png": None, "data": {"price": px, "entry": r["entry"], "mode": tag}})
    return True


def run(stage="4h", rules=None, now=None, client=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    rows = store.read("positions.csv"); n_exit = n_stale = n_int = 0
    held = executor_held(rules)
    if guard_mod.is_killed():
        for r in rows:
            if r.get("status") != "OPEN": continue
            dec = decision_for(r["plan_id"])
            px = store.f(r.get("entry"))
            try:
                px = market.last_price(r["coin"], client) or px
            except Exception:
                pass
            if _alert("EXIT_NOW", r, "KILL_SWITCH", float(px or r["entry"]), rules, dec, held) is False: n_int += 1
            n_exit += 1
            auditor.close_paper(r, float(px or r["entry"]), now, "KILL_SWITCH", rules, dec)
        store.write("positions.csv", rows)
        log(f"exit_clerk ({stage}): KILL_SWITCH — {n_exit} posições encerradas ({n_int} sem alerta: fora do executor)")
        return n_exit, 0
    for r in rows:
        if r["status"] != "OPEN": continue
        p = to_pos(r); dec = decision_for(r["plan_id"])
        last = int(r["last_h1"]) if r["last_h1"] else p.opened_ts - L.H
        h1 = [c for c in market.candles(p.symbol, 60, 0, now, client, since=last + 1) if c["start"] > last]
        d1 = market.candles(p.symbol, 1440, 3, now, client)
        last_d = int(r["last_d1"]) if r["last_d1"] else p.opened_ts - L.D
        daily_new = [c for c in d1 if c["start"] > last_d and c["start"] + L.D > p.opened_ts]
        exit_ = None
        for c in h1:
            # fecho diário que ocorre ANTES desta vela 1H -> regra da âncora
            for d in [d for d in daily_new if d["start"] + L.D <= c["start"]]:
                daily_new.remove(d); r["last_d1"] = d["start"]
                if L.daily_anchor_exit(p, d["close"]): exit_ = ("ANCHOR_1D_CLOSE", d["close"], d["start"] + L.D); break
            if exit_: break
            ex = L.check_exit(p, c, rules)
            r["last_h1"] = c["start"]
            if ex: exit_ = (ex[0], ex[1], c["start"] + L.H); break
            L.after_bar(p, c, rules)
        if not exit_ and stage == "daily":
            for d in daily_new:
                r["last_d1"] = d["start"]
                if L.daily_anchor_exit(p, d["close"]): exit_ = ("ANCHOR_1D_CLOSE", d["close"], d["start"] + L.D); break
        update_row(r, p)
        if exit_:
            rule, px, ts = exit_
            if _alert("EXIT_NOW", r, rule, px, rules, dec, held) is False: n_int += 1
            n_exit += 1
            auditor.close_paper(r, px, ts, rule, rules, dec)
        elif h1 and not p.stale_flagged and L.is_stale(p, now, h1[-1]["close"], rules):
            p.stale_flagged = True; update_row(r, p)
            if _alert("STALE", r, "FLAT_72H", h1[-1]["close"], rules, dec, held) is False: n_int += 1
            n_stale += 1
    store.write("positions.csv", rows)
    log(f"exit_clerk ({stage}): {n_exit} EXIT NOW, {n_stale} STALE" + (f" ({n_int} internos: fora do executor)" if n_int else ""))
    return n_exit, n_stale


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", default="4h", choices=["4h", "daily"]); a = ap.parse_args()
    run(a.stage)


if __name__ == "__main__":
    main()
