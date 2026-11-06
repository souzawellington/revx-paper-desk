"""Estudo pré-registado do contexto macro (DESK_RULES.md, secção «Contexto macro»). Não altera o desk live.
python -m desk.macro_study [--quick]  -> desk/state/macro_report.md + macro_report.json
"""
from __future__ import annotations
import argparse, json, os
from .rules import load_rules, Rules
from . import replay, community, macro as MACRO, store
from .tournament import summarize
from .findings import label_finding

UNIVERSES = [("revolutx_1y_15", "data", None), ("coinbase_3y_15", "data_ext/coinbase", None),
             ("coinbase_3y_majors", "data_ext/coinbase", ["BTC-USD", "ETH-USD", "SOL-USD"])]


def _syms(data_dir, only):
    if only: return only
    return sorted(f[len("candles_"):-len("_60.json")] for f in os.listdir(data_dir) if f.startswith("candles_") and f.endswith("-USD_60.json"))


def _row(sid, sc, r):
    fake = {"n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"], "expectancy_r": sc["full"]["expectancy_r"], "max_dd": sc["max_dd"],
            "go": sc.get("go", False), "thresholds": {k: (None, v) for k, v in sc.get("thresholds_pass", {}).items()}}
    return {"id": sid, "n": sc["full"]["n"], "win_rate": sc["full"]["win_rate"], "exp": sc["full"]["expectancy_r"],
            "oos_n": sc["oos"]["n"], "oos_wr": sc["oos"]["win_rate"], "oos_exp": sc["oos"]["expectancy_r"],
            "is_n": sc["in_sample"]["n"], "is_exp": sc["in_sample"]["expectancy_r"],
            "max_dd": sc["max_dd"], "pnl": sc["full"].get("pnl_usd"), "finding": label_finding(fake, r, sc["oos"]),
            "macro_vetoes": sc.get("macro_vetoes")}


def run(quick=False):
    base = load_rules(); ctx = MACRO.load(); out = {"universes": {}}
    for name, dd, only in (UNIVERSES[:1] if quick else UNIVERSES):
        syms = _syms(dd, only); rows = []
        for sid, ov in [("01_desk_fvg_long", {"macro_mode": "shadow"}),
                        ("21_fvg_macro_veto", {"macro_mode": "enforce", "macro_veto_flags": 2}),
                        ("22_fvg_macro_strict", {"macro_mode": "enforce", "macro_veto_flags": 1})]:
            r = Rules({**base.p, "take_profit_r": 4, "no_hero": True, **ov})
            res = replay.run(syms, r, dd, macro_ctx=ctx); sc = replay.score(res, r)
            row = _row(sid, sc, r)
            if sid.startswith("01"): row["macro_shadow"] = sc["macro_shadow"]
            rows.append(row)
        # 09 vs 23 (filtro no sinal; R = retorno líquido / 8%)
        all_tr = []
        for s in syms: all_tr += community.bbandrsi(replay.load_cached(s, dd), base)
        r2 = Rules({**base.p, "macro_veto_flags": 2})
        tagged = [{**t, "macro": MACRO.evaluate(ctx, t["entry_ts"], r2)["status"]} for t in all_tr]
        kept = [t for t in tagged if t["macro"] != MACRO.RISK_OFF]
        for sid, trs in (("09_bbandrsi", tagged), ("23_bbandrsi_macro", kept)):
            sm = summarize(trs); sc = {"full": sm["full"], "oos": sm["oos"], "in_sample": sm["in_sample"], "max_dd": sm["full"]["max_dd"],
                                      "thresholds_pass": {"trades": sm["full"]["n"] >= base.threshold_trades,
                                                          "win_rate": sm["full"]["win_rate"] >= base.threshold_win_rate,
                                                          "expectancy": sm["full"]["expectancy_r"] >= base.threshold_expectancy_r,
                                                          "max_dd": sm["full"]["max_dd"] <= base.threshold_max_dd}}
            sc["go"] = all(sc["thresholds_pass"].values()); rows.append(_row(sid, sc, base))
        out["universes"][name] = {"symbols": syms, "rows": rows}
    btc = json.load(open(os.path.join(MACRO.DEFAULT_DIR, "btc_daily.json")))["bars"] if os.path.exists(os.path.join(MACRO.DEFAULT_DIR, "btc_daily.json")) else []
    out["btc_forward_30d"] = MACRO.btc_forward_study(ctx, btc, base, 30) if btc else None
    return out


def write(out, path):
    L = ["# Contexto macro (OpenBB / yfinance) — estudo pré-registado", "",
         "Pré-registo: DESK_RULES.md, secção «Contexto macro» (escrito antes de descarregar dados macro). Parâmetros não afinados.",
         "R líquido (fees 0.09% + slippage 0.1% por lado). Holdout 60/40 por tempo. Limiares congelados.", ""]
    for name, u in out["universes"].items():
        L += [f"## {name} ({len(u['symbols'])} pares)", "",
              "| spec | n | WR | exp R | IS n / exp | OOS n / WR / exp | max DD | vetos macro | finding |", "|---|---|---|---|---|---|---|---|---|"]
        for r in u["rows"]:
            L.append(f"| {r['id']} | {r['n']} | {r['win_rate']:.1%} | {r['exp']:+.3f} | {r['is_n']} / {r['is_exp']:+.3f} | "
                     f"{r['oos_n']} / {r['oos_wr']:.1%} / {r['oos_exp']:+.3f} | {r['max_dd']:.1%} | {r['macro_vetoes'] if r['macro_vetoes'] is not None else '–'} | **{r['finding']}** |")
        ms = next((r.get("macro_shadow") for r in u["rows"] if r.get("macro_shadow")), None)
        if ms:
            L += ["", "Shadow (01, estado macro no alerta): " + "; ".join(
                f"{k}: n={v['full']['n']} exp {v['full']['expectancy_r']:+.3f}R" + (f" (OOS n={v['oos']['n']} {v['oos']['expectancy_r']:+.3f}R)" if 'oos' in v else "")
                for k, v in sorted(ms.items()))]
        L.append("")
    b = out.get("btc_forward_30d")
    if b:
        L += ["## BTC-USD diário (yfinance, desde 2014): retorno a 30 dias por estado macro", "",
              "| amostra | estado | n dias | média 30d | % positivos |", "|---|---|---|---|---|"]
        for part in ("in_sample", "oos"):
            for st, v in b[part].items():
                L.append(f"| {part} | {st} | {v['n']} | {v['mean']:+.2%} | {v['hit']:.1%} |")
        L.append("")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true"); a = ap.parse_args()
    out = run(a.quick); p = store.path("macro_report.md"); write(out, p)
    json.dump(out, open(p.replace(".md", ".json"), "w"), indent=2, default=str); print(open(p).read())


if __name__ == "__main__":
    main()
