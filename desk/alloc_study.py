"""Estudo pré-registado HRP/CVaR (DESK_RULES.md, secção «Alocação HRP»). Não altera o desk live.
python -m desk.alloc_study  -> desk/state/alloc_report.md + alloc_report.json"""
from __future__ import annotations
import json
from .rules import load_rules, Rules
from . import replay, store
from .macro_study import UNIVERSES, _syms

SPECS = [("01_desk_fvg_long", {"alloc_mode": "off"}), ("24_fvg_hrp_mv", {"alloc_mode": "enforce", "alloc_rm": "MV"}),
         ("25_fvg_hrp_cvar", {"alloc_mode": "enforce", "alloc_rm": "CVaR"})]


def run():
    base = load_rules(); out = {}
    for name, dd, only in UNIVERSES:
        syms = _syms(dd, only); rows = []
        for sid, ov in SPECS:
            r = Rules({**base.p, "take_profit_r": 4, "no_hero": True, "macro_mode": "off", **ov})
            res = replay.run(syms, r, dd); sc = replay.score(res, r); m = sc["metrics"]["curve"]
            caps = [t for t in res["trades"]]
            rows.append({"id": sid, "n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"], "exp": sc["full"]["expectancy_r"],
                         "oos_exp": sc["oos"]["expectancy_r"], "pnl": sc["full"]["pnl_usd"], "oos_pnl": sc["oos"]["pnl_usd"],
                         "max_dd": sc["max_dd"], "ulcer": m.get("ulcer_index"), "cvar95_daily": m.get("cvar95_daily"),
                         "sortino_ann": m.get("sortino_ann"), "avg_notional": sum(t["qty"] * t["entry"] for t in caps) / len(caps) if caps else 0})
        out[name] = {"symbols": syms, "rows": rows}
    return out


def write(out, path):
    L = ["# HRP / CVaR (Riskfolio-Lib) — estudo pré-registado", "",
         "Pré-registo: DESK_RULES.md, secção «Alocação HRP». O redutor de tamanho não muda R por trade; mede-se PnL e risco da curva.", ""]
    for name, u in out.items():
        L += [f"## {name} ({len(u['symbols'])} pares)", "", "| spec | n | WR | exp R | OOS exp R | PnL USD | PnL OOS | notional médio | max DD | Ulcer | CVaR95 diário | Sortino anual |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in u["rows"]:
            g = lambda v, f: "–" if v is None else f.format(v)
            L.append(f"| {r['id']} | {r['n']} | {r['win_rate']:.1%} | {r['exp']:+.3f} | {r['oos_exp']:+.3f} | {r['pnl']:+.0f} | {r['oos_pnl']:+.0f} | "
                     f"{r['avg_notional']:.0f} | {r['max_dd']:.1%} | {g(r['ulcer'], '{:.3f}')} | {g(r['cvar95_daily'], '{:+.2%}')} | {g(r['sortino_ann'], '{:+.2f}')} |")
        L.append("")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    out = run(); p = store.path("alloc_report.md"); write(out, p)
    json.dump(out, open(p.replace(".md", ".json"), "w"), indent=2); print(open(p).read())


if __name__ == "__main__":
    main()
