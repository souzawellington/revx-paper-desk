"""Papel 4 — GATE. Único papel que fala com o humano (via outbox.jsonl, que o agente reencaminha).
Para cada linha nova de trade_plan.csv: UM alerta (coin | zona | entrada | stop | tamanho | risco % | gráfico).
Regista TAKEN/SKIPPED em decisions.csv via `python -m desk decide <id> TAKEN|SKIPPED`.
NUNCA envia nada à exchange: não tem permissão e nunca a pede."""
from __future__ import annotations
import argparse
from .rules import load_rules
from . import market, store, charts, logic as L
from .roles import guard as guard_mod
from . import panel as PANEL
from . import macro as MACRO
from . import allocation as ALLOC
from . import debate as DEBATE
import json, os


def alert_id(plan_id): return f"ENTRY:{plan_id}"


def run(rules=None, now=None, client=None, log=print):
    rules = rules or load_rules(); now = now or store.now_ms()
    g = guard_mod.check(rules, now, log)
    if not g["ok"]:
        log(f"gate: bloqueado pelo GUARD ({';'.join(g['reasons'])}) — nenhum ENTRY novo")
        return 0
    sent = store.outbox_ids(); zones = store.read("zones.csv"); n = 0
    for p in store.read("trade_plan.csv"):
        aid = alert_id(p["plan_id"])
        if aid in sent: continue
        z = next((z for z in zones if z["zone_id"] == p["zone_id"]), {})
        coin_z = [x for x in zones if x["coin"] == p["coin"] and x["status"] not in ("DROPPED", "INVALID")]
        png = None
        try:
            h4 = market.candles(p["coin"], 240, rules.gate_chart_bars_4h, now, client)
            png = charts.render(p["coin"], h4, coin_z, float(p["entry"]), float(p["stop"]), store.f(p["anchor_low"]),
                                f"{p['coin']} · zona {z.get('zone_bottom', '?')}–{z.get('zone_top', '?')} · add #{p['add_number']}",
                                aid.replace(":", "_") + ".png", rules.gate_chart_bars_4h, tp=store.f(p.get("tp_price")))
        except Exception as e:
            log(f"gate: gráfico falhou para {p['coin']}: {e}")
        risk_usd = float(p["size"]) * (float(p["entry"]) - float(p["stop"]))
        tp = store.f(p.get("tp_price"))
        if tp is None:
            tp = L.tp_price(float(p["entry"]), float(p["stop"]), rules.take_profit_r)
        r_mult = rules.take_profit_r
        pdec = None
        try: pdec = json.loads(p["panel"]) if p.get("panel") else None
        except Exception: pdec = None
        pline = (PANEL.summary(pdec) + "\n") if pdec else ""
        try: prot = json.loads(p["prot"]) if p.get("prot") else None
        except Exception: prot = None
        if prot:
            pline += (f"Protections ({prot.get('mode')}): " + (", ".join(prot["reasons"]) if prot["reasons"] else "OK — nenhum bloqueio") + "\n")
        try: mac = json.loads(p["macro"]) if p.get("macro") else None
        except Exception: mac = None
        if mac: pline += MACRO.summary(mac) + "\n"
        try: alc = json.loads(p["alloc"]) if p.get("alloc") else None
        except Exception: alc = None
        if alc: pline += ALLOC.summary(alc) + "\n"
        deb = None
        if rules.p.get("debate_record", False):   # desligado por defeito
            try: deb = DEBATE.record(p, rules); pline += DEBATE.line(deb) + "\n"
            except Exception as e: log(f"gate: debate falhou ({type(e).__name__})")
        auto = str(rules.p.get("execution_mode", "off")) != "off"
        head = (f"🤖 ENTRY ({rules.p.get('execution_mode')}: o executor autónomo trata desta entrada; não é preciso TAKEN/SKIPPED)\n"
                if auto else "🟢 ENTRY ALERT (alerta apenas; não há execução automática)\n")
        text = (head +
                f"{p['coin']} | zona {float(z.get('zone_bottom', 0)):.6g}–{float(z.get('zone_top', 0)):.6g} | entrada {float(p['entry']):.6g} | "
                f"stop {float(p['stop']):.6g} | TP {tp:.6g} (+{r_mult:g}R) | tamanho {float(p['size']):.8g} ({float(p['notional']):,.2f} {rules.quote}) | "
                f"risco planeado {float(p['risk_pct']) * 100:.2f}% · efetivo {risk_usd / float(p['equity']) * 100:.2f}% (≈{risk_usd:,.2f} {rules.quote}) | add #{p['add_number']}\n"
                f"Âncora 1D {float(p['anchor_low']):.6g} · equity {p['equity_source']} {float(p['equity']):,.2f} · limitado por {p['sizing_binding']}\n"
                f"{pline}"
                f"Stop e TP pré-comprometidos (immutáveis após TAKEN, excepto BE no stop).\n"
                + ("Notificação apenas." if auto else f"Responder: TAKEN ou SKIPPED  (python -m desk decide {aid} TAKEN|SKIPPED)"))
        store.emit({"id": aid, "type": "ENTRY_ALERT", "coin": p["coin"], "plan_id": p["plan_id"], "text": text, "chart_png": png,
                    "data": {**{k: p[k] for k in ("entry", "stop", "tp_price", "size", "notional", "risk_pct", "add_number", "anchor_low", "zone_id", "equity", "equity_source", "sizing_binding")},
                             "zone_top": z.get("zone_top"), "zone_bottom": z.get("zone_bottom"), "effective_risk_pct": risk_usd / float(p["equity"]),
                             "take_profit_r": r_mult, "panel": pdec, "protections": prot, "macro": mac, "alloc": alc, "debate": deb},
                    "reply_options": [] if auto else ["TAKEN", "SKIPPED"], "autonomous": auto})
        n += 1
    log(f"gate: {n} alertas novos no outbox")
    return n


def decide(alert_id_: str, decision: str):
    decision = decision.upper()
    if decision not in ("TAKEN", "SKIPPED"): raise SystemExit("decisão tem de ser TAKEN ou SKIPPED")
    a = next((x for x in store.outbox() if x["id"] == alert_id_), None)
    if not a or a["type"] != "ENTRY_ALERT": raise SystemExit(f"alerta {alert_id_} não encontrado")
    if any(d["alert_id"] == alert_id_ for d in store.read("decisions.csv")): raise SystemExit("decisão já registada")
    store.append("decisions.csv", [{"ts": store.iso(store.now_ms()), "alert_id": alert_id_, "plan_id": a["plan_id"], "decision": decision}])
    store.ack(alert_id_)
    print(f"{alert_id_} -> {decision}")


def main():
    ap = argparse.ArgumentParser(); ap.parse_args(); run()


if __name__ == "__main__":
    main()
