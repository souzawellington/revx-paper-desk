"""Papel 6 — AUDITOR. Dono: o journal.
- Regista cada trade com entrada, saída, taxa e slippage em LINHAS SEPARADAS, mais o resultado em R.
- Em paper simula automaticamente o fill de TODOS os planos (abertura da vela 1H seguinte), para acumular a contagem de 40.
- Regista também os alertas SKIPPED e o que teriam rendido (modo HYPOTHETICAL_SKIPPED).
- Relatório semanal contra os limiares CONGELADOS do DESK_RULES.md. Nunca sugere mudar um limiar."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from .rules import load_rules
from . import logic as L, market, store
from .positions import decision_for


def paper_fill(rules=None, now=None, client=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    rows = store.read("positions.csv"); have = {r["plan_id"] for r in rows}; new = []
    for p in store.read("trade_plan.csv"):
        if p["plan_id"] in have: continue
        t0 = int(float(p["created_ts"]))
        nxt = [c for c in market.candles(p["coin"], 60, 0, now, client, since=t0) if c["start"] >= t0]
        if not nxt: continue   # ainda não há abertura seguinte
        c = nxt[0]; fill = c["open"]; stop = float(p["stop"])
        if fill <= stop:
            store.append("journal.csv", [{"ts": store.iso(c["start"]), "trade_id": p["plan_id"], "coin": p["coin"], "line": "VOID",
                                          "price": fill, "note": "abertura <= stop; sem entrada", "mode": "PAPER", "tag": p.get("tag") or ""}])
            rows.append({"pid": p["plan_id"], "plan_id": p["plan_id"], "coin": p["coin"], "status": "VOID", "tag": p.get("tag") or ""}); continue
        qty = float(p["size"])
        # TP pré-comprometido do plano; se o fill diferir da entrada planeada, recalcular TP com o MESMO R do plano
        # (take_profit_r × risco do plano) para manter a assimetria 1:N — stop absoluto do plano, TP relativo ao fill.
        plan_entry, plan_stop = float(p["entry"]), stop
        plan_r = plan_entry - plan_stop
        if "tp_price" in p and p["tp_price"] not in ("", None) and abs(fill - plan_entry) < 1e-12:
            tp = float(p["tp_price"])
        else:
            tp = fill + rules.take_profit_r * plan_r
        # stop do plano mantém-se (pré-comprometido); se fill <= stop → VOID acima
        rows.append({"pid": p["plan_id"], "plan_id": p["plan_id"], "coin": p["coin"], "status": "OPEN", "entry": fill, "stop": stop,
                     "initial_stop": stop, "tp_price": tp, "qty": qty, "risk_pct": p["risk_pct"], "add_number": p["add_number"],
                     "anchor_low": p["anchor_low"], "opened_ts": c["start"], "peak": fill, "at_be": False, "stale_flagged": False,
                     "last_h1": c["start"] - L.H, "last_d1": "", "tag": p.get("tag") or ""})
        new.append(p["plan_id"])
    store.write("positions.csv", rows)
    log(f"auditor: {len(new)} fills paper simulados")
    return new


def close_paper(r, px, ts, rule, rules, decision):
    entry, stop, qty = float(r["entry"]), float(r["initial_stop"]), float(r["qty"])
    x = L.trade_r(entry, px, stop, rules)
    mode = "HYPOTHETICAL_SKIPPED" if decision == "SKIPPED" else "PAPER"
    pnl = qty * (x["fill_out"] - x["fill_in"]) - qty * x["fee_per_unit"]
    base = {"trade_id": r["pid"], "coin": r["coin"], "mode": mode, "decision": decision, "qty": qty, "tag": r.get("tag") or ""}
    store.append("journal.csv", [
        {**base, "ts": store.iso(int(r["opened_ts"])), "line": "ENTRY", "price": entry, "amount_usd": -qty * entry,
         "note": f"stop {stop} tp {r.get('tp_price', '')}"},
        {**base, "ts": store.iso(ts), "line": "EXIT", "price": px, "amount_usd": qty * px, "note": rule},
        {**base, "ts": store.iso(ts), "line": "FEE", "amount_usd": -qty * x["fee_per_unit"], "note": f"taker {rules.taker_fee:.4%} x2"},
        {**base, "ts": store.iso(ts), "line": "SLIPPAGE", "amount_usd": -qty * x["slippage_per_unit"], "note": f"{rules.slippage:.3%} por lado"},
        {**base, "ts": store.iso(ts), "line": "RESULT", "amount_usd": pnl, "r": round(x["net_r"], 4), "note": f"bruto {x['gross_r']:.3f}R"},
    ])
    r.update(status="CLOSED", exit=px, exit_ts=ts, exit_rule=rule)


def record_manual_close(pid, price, rules=None):
    """Para posições TAKEN fechadas pelo humano na app: regista o preço real de saída."""
    rules = rules or load_rules(); rows = store.read("positions.csv")
    r = next((x for x in rows if x["pid"] == pid), None)
    if not r: raise SystemExit("pid não encontrado")
    store.append("journal.csv", [{"ts": store.iso(store.now_ms()), "trade_id": pid, "coin": r["coin"], "line": "MANUAL_EXIT",
                                  "price": price, "mode": "LIVE", "decision": "TAKEN", "note": "saída real informada pelo humano"}])
    if r["status"] == "OPEN": close_paper(r, float(price), store.now_ms(), "MANUAL", rules, "TAKEN")
    store.write("positions.csv", rows)


def stats(rules, modes=("PAPER",), tag=None):
    """tag=None: todos (é o que decide o GO); tag="paper_fast" / "": só esse grupo (descritivo)."""
    res = [r for r in store.read("journal.csv") if r["line"] == "RESULT" and r["mode"] in modes
           and (tag is None or (r.get("tag") or "") == tag)]
    res.sort(key=lambda r: r["ts"])
    n = len(res); rs = [float(r["r"]) for r in res]
    eq = peak = rules.paper_equity; mdd = 0.0
    for r in res:
        eq += float(r["amount_usd"]); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    win = sum(1 for x in rs if x > 0) / n if n else 0.0; exp = sum(rs) / n if n else 0.0
    th = {"trades": (n, n >= rules.threshold_trades), "win_rate": (win, win >= rules.threshold_win_rate),
          "expectancy_r": (exp, exp >= rules.threshold_expectancy_r), "max_dd": (mdd, mdd <= rules.threshold_max_dd)}
    from .metrics import trade_metrics
    return {"n": n, "win_rate": win, "expectancy_r": exp, "max_dd": mdd, "equity": eq, "thresholds": th,
            "go": all(v[1] for v in th.values()), "metrics": trade_metrics(rs)}   # métricas: só descritivas



def rebuild_skipped_stats(rules=None, log=print):
    """Rolling stats de RESULT mode=HYPOTHETICAL_SKIPPED por moeda → skipped_stats.json."""
    rules = rules or load_rules()
    by = {}
    for r in store.read("journal.csv"):
        if r.get("line") != "RESULT" or r.get("mode") != "HYPOTHETICAL_SKIPPED": continue
        c = r["coin"]; by.setdefault(c, [])
        by[c].append(store.f(r.get("r"), 0.0))
    out = {"generated_at": store.iso(store.now_ms()), "by_coin": {}}
    for c, rs in by.items():
        n = len(rs); out["by_coin"][c] = {"n": n, "expectancy_r": sum(rs) / n if n else 0.0,
                                          "win_rate": sum(1 for x in rs if x > 0) / n if n else 0.0}
    path = store.path("skipped_stats.json")
    json.dump(out, open(path, "w"), indent=2)
    log(f"auditor: skipped_stats {len(out['by_coin'])} moedas → {path}")
    return out

def _tag_line(rules):
    """Separação dos trades do ensaio acelerado (tag paper_fast) — os limiares e o GO NÃO mudam."""
    from .rules import PAPER_FAST_TAG
    f, n = stats(rules, tag=PAPER_FAST_TAG), stats(rules, tag="")
    return (f"Ensaio acelerado ({PAPER_FAST_TAG}: até {rules.p.get('paper_max_open_positions', rules.max_open_positions)} posições, "
            f"mesmo risco 1%): {f['n']} trades, WR {f['win_rate']:.1%}, {f['expectancy_r']:+.3f}R · "
            f"normais: {n['n']} trades, WR {n['win_rate']:.1%}, {n['expectancy_r']:+.3f}R. "
            f"O veredito acima conta os dois; só com os normais seria {'GO' if n['go'] else 'NO-GO'}.")


def weekly(rules=None, now=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    rebuild_skipped_stats(rules, log)
    s = stats(rules); sk = stats(rules, ("HYPOTHETICAL_SKIPPED",))
    from .findings import label_finding, format_finding_line
    finding = label_finding(s, rules)
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    ok = lambda b: "PASSA" if b else "FALHA"
    lines = [f"# Relatório semanal do desk — {day}", "",
             "Limiares CONGELADOS (DESK_RULES.md). O Auditor não sugere alterá-los.", "",
             "| Métrica | Valor | Limiar | Estado |", "|---|---|---|---|",
             f"| Trades (paper) | {s['n']} | ≥ {rules.threshold_trades} | {ok(s['thresholds']['trades'][1])} |",
             f"| Win rate | {s['win_rate']:.1%} | ≥ {rules.threshold_win_rate:.0%} | {ok(s['thresholds']['win_rate'][1])} |",
             f"| Expectancy | {s['expectancy_r']:+.3f}R | ≥ +{rules.threshold_expectancy_r}R | {ok(s['thresholds']['expectancy_r'][1])} |",
             f"| Max DD | {s['max_dd']:.1%} | ≤ {rules.threshold_max_dd:.0%} | {ok(s['thresholds']['max_dd'][1])} |", "",
             f"Veredito: {'GO (desbloqueia tamanho real)' if s['go'] else 'NO-GO (continuar em paper)'}.",
             format_finding_line(finding),
             _tag_line(rules),
             f"Alertas SKIPPED (hipotéticos): {sk['n']} trades, expectancy {sk['expectancy_r']:+.3f}R.",
             "Métricas descritivas (FinanceToolkit; não mudam o GO): " + __import__("desk.metrics", fromlist=["fmt"]).fmt(s.get("metrics") or {}) + ".",
             f"Equity paper: {s['equity']:,.2f} {rules.quote}."]
    d = os.path.join(store.STATE, "reports"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"weekly_{day}.md"); open(p, "w").write("\n".join(lines) + "\n")
    store.emit({"id": f"WEEKLY:{day}", "type": "WEEKLY_REPORT", "coin": None, "text": "\n".join(lines), "chart_png": None,
                "data": {"n_paper_fast": stats(rules, tag="paper_fast")["n"], "n": s["n"], "win_rate": s["win_rate"], "expectancy_r": s["expectancy_r"], "max_dd": s["max_dd"], "go": s["go"], "finding": finding},
                "report_path": p})
    log(f"auditor: relatório {p} ({'GO' if s['go'] else 'NO-GO'})")
    return s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--weekly", action="store_true"); a = ap.parse_args()
    weekly() if a.weekly else paper_fill()


if __name__ == "__main__":
    main()
