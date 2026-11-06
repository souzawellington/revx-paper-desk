"""REGISTO DE DEBATE + MEMÓRIA (ideias de TauricResearch/TradingAgents, Apache-2.0 — estrutura, não código).

O TradingAgents usa LLMs: analistas → debate bull/bear → trader → equipa de risco (agressivo/neutro/conservador) →
portfolio manager, mais um "memory log" que liquida decisões passadas e gera reflexões. Aqui fica a versão
DETERMINÍSTICA e sem LLM (nenhuma chamada paga), construída só a partir das camadas que já existem no plano
(painel, macro, protections, HRP, custos):
- `record(plan, rules)`: caso bull / caso bear (cada ponto cita a métrica de onde vem), três vistas de risco
  (agressivo = tamanho do plano, nunca acima; neutro = só o painel; conservador = o menor de todas as camadas) e o
  veredito que as camadas em `enforce` aplicariam. Nunca aumenta; nunca coloca ordens; texto externo não entra
  (se entrar no futuro, só via untrusted_wrap).
- `settle(rules)`: "memória" — junta cada plano com o resultado no journal (PAPER e HYPOTHETICAL_SKIPPED) e mede,
  por camada e por ação (VETO/REDUCE/KEEP…), o R realizado. Reflexões em texto fixo, sem LLM.
`debate_record: false` (defeito): o gate não acrescenta a linha de debate. `settle` é um relatório só-leitura.
python -m desk.debate settle   -> desk/state/debate_memory.md + .json
"""
from __future__ import annotations
import argparse, json
from . import store, logic as L


def _j(x):
    if isinstance(x, dict) or x is None: return x
    try: return json.loads(x) if x else None
    except Exception: return None


def record(plan: dict, rules) -> dict:
    pan, mac, prot, alc = (_j(plan.get(k)) for k in ("panel", "macro", "prot", "alloc"))
    bull, bear = [], []
    entry, stop = float(plan["entry"]), float(plan["stop"])
    ev = L.expected_ev_r_for_plan(entry, stop, float(rules.take_profit_r), rules)
    bull.append(f"setup PRIME+CONFIRMED, TP {rules.take_profit_r:g}R pré-comprometido")
    (bull if ev > 0.25 else bear).append(f"EV planeado após custos {ev:+.2f}R (p={rules.threshold_win_rate:.0%})")
    views = {"aggressive": 1.0}
    if pan:
        for v in pan.get("votes", []):
            if v["signal"] == "bullish": bull.append(f"{v['analyst']} bullish ({v['confidence']:.2f}) {v.get('metrics', {})}")
            elif v["signal"] == "bearish": bear.append(f"{v['analyst']} bearish ({v['confidence']:.2f}) {v.get('metrics', {})}")
        views["neutral"] = float(pan.get("size_mult", 1.0))
    else:
        views["neutral"] = 1.0
    cons = [views["neutral"]]
    if mac:
        if mac.get("flags"): bear.append("macro " + ",".join(mac["flags"]))
        elif mac.get("status") == "OK": bull.append("macro OK (sem flags)")
        cons.append(float(mac.get("size_mult", 1.0)))
    if prot:
        if prot.get("reasons"): bear.append("protections " + ",".join(prot["reasons"])); cons.append(0.0)
        else: bull.append("protections sem bloqueios")
    if alc and alc.get("status") == "OK":
        cap = float(alc["cap_frac"]); mpf = float(rules.max_position_frac)
        if cap < mpf - 1e-9: bear.append(f"HRP corta teto para {cap:.1%}"); cons.append(cap / mpf)
    views["conservative"] = max(0.0, min(cons))
    views = {k: min(1.0, v) for k, v in views.items()}   # ninguém aumenta
    w = views["conservative"]
    verdict = "VETO" if w == 0 else "REDUCE" if w < 1 else "KEEP"
    return {"bull": bull, "bear": bear, "risk_views": views, "would": verdict, "size_mult_conservative": round(w, 4),
            "balance": len(bull) - len(bear)}


def line(rec) -> str:
    return (f"Debate: {len(rec['bull'])} bull / {len(rec['bear'])} bear → conservador {rec['would']} ×{rec['size_mult_conservative']:.2f}"
            + (f" | bear: {'; '.join(rec['bear'][:3])}" if rec["bear"] else ""))


def settle(rules, plans=None, journal=None):
    plans = plans if plans is not None else store.read("trade_plan.csv")
    journal = journal if journal is not None else store.read("journal.csv")
    res = {r["trade_id"]: (store.f(r.get("r"), 0.0), r.get("mode")) for r in journal if r.get("line") == "RESULT"}
    layers = {}
    def add(layer, action, r):
        layers.setdefault(layer, {}).setdefault(action, []).append(r)
    n = 0
    for p in plans:
        if p["plan_id"] not in res: continue
        r, _mode = res[p["plan_id"]]; n += 1
        pan, mac, prot, alc = (_j(p.get(k)) for k in ("panel", "macro", "prot", "alloc"))
        add("panel", (pan or {}).get("action", "NONE"), r)
        add("macro", (mac or {}).get("status", "NONE"), r)
        add("protections", "NONE" if prot is None else ("BLOCK" if prot.get("reasons") else "PASS"), r)
        add("hrp", "NONE" if not alc else ("CUT" if alc.get("status") == "OK" and float(alc["cap_frac"]) < float(rules.max_position_frac) - 1e-9 else alc.get("status", "NONE")), r)
        add("debate", record(p, rules)["would"], r)
    out = {"settled": n, "layers": {}}
    lessons = []
    for layer, acts in layers.items():
        out["layers"][layer] = {a: {"n": len(v), "mean_r": sum(v) / len(v), "win_rate": sum(1 for x in v if x > 0) / len(v)} for a, v in acts.items()}
        blk = [x for a, v in acts.items() if a in ("VETO", "BLOCK", "RISK_OFF", "CUT", "REDUCE") for x in v]
        ok = [x for a, v in acts.items() if a in ("KEEP", "PASS", "OK") for x in v]
        if len(blk) >= 5 and len(ok) >= 5:
            d = sum(blk) / len(blk) - sum(ok) / len(ok)
            lessons.append(f"{layer}: trades que a camada travaria/cortaria renderam {d:+.2f}R vs os aprovados "
                           + ("(a camada acertou)" if d < 0 else "(a camada teria custado R)"))
        else:
            lessons.append(f"{layer}: amostra insuficiente (travados {len(blk)}, aprovados {len(ok)}; mínimo 5/5)")
    out["lessons"] = lessons
    return out


def write(out, path):
    L_ = ["# Memória das decisões (estilo TradingAgents, determinística)", "", f"Planos liquidados: {out['settled']}", "",
          "| camada | ação | n | R médio | WR |", "|---|---|---|---|---|"]
    for layer, acts in out["layers"].items():
        for a, v in sorted(acts.items()):
            L_.append(f"| {layer} | {a} | {v['n']} | {v['mean_r']:+.3f} | {v['win_rate']:.0%} |")
    L_ += ["", "## Reflexões", ""] + [f"- {x}" for x in out["lessons"]] + [""]
    open(path, "w").write("\n".join(L_) + "\n")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["settle"]); ap.parse_args()
    from .rules import load_rules
    out = settle(load_rules()); p = store.path("debate_memory.md"); write(out, p)
    json.dump(out, open(p.replace(".md", ".json"), "w"), indent=2); print(open(p).read())


if __name__ == "__main__":
    main()
