"""Critérios de morte (paragem automática) + teto de saldo — partilhado pelo executor (Bot D) e pelos bots-sombra C3/B&H (A/B).

Pedido do utilizador (2026-10-20). Tudo paper; nada aqui coloca ordens, deposita ou levanta.
  * Teto: `target_balance` (DESK_RULES; env BOT_TARGET_BALANCE sobrepõe no executor) = 1000 USD. Ao atingir → pausa trancada +
    notificação «teto atingido, sacar e deixar o saldo inicial». Retoma SÓ com rebase manual para `reset_balance` (65 USD ≈ £50).
  * Critérios (cada bot):  DD forward > kill_dd_max (20%; C3 com tetos mantém 14%, mais estrito) | Sharpe 12 meses < 0 |
    divergência paper vs referência > 2 p.p. em 30 dias | dados Revolut X ausentes/stale > 3 dias |
    erros de API recorrentes (falhas consecutivas ≥ kill_api_fail_min_runs E a durar ≥ kill_api_fail_hours h; OU taxa de
    falha ≥ kill_api_rate_max nos últimos kill_api_rate_days dias com ≥ kill_api_rate_min_runs execuções).
    A falha 502 de 3 h de 2026-10-20 (3–4 execuções horárias) NÃO dispara: são precisas ≥ 24 h seguidas a falhar.

python -m desk.health [--json]   → só leitura: equity de cada bot, distância ao teto, cada critério (valor vs limite, ON/OFF).
"""
from __future__ import annotations
import csv, json, math, os, sys
from datetime import datetime, timezone

from desk import store

D, H = 86_400_000, 3_600_000
DEFAULTS = {"target_balance": 1000.0, "reset_balance": 65.0, "kill_dd_max": 0.20, "kill_sharpe_days": 365,
            "kill_diverge_days": 30, "kill_diverge_max": 0.02, "kill_data_stale_days": 3, "kill_api_fail_hours": 24,
            "kill_api_fail_min_runs": 3, "kill_api_rate_days": 7, "kill_api_rate_max": 0.5, "kill_api_rate_min_runs": 20}
RUNS_KEEP = 400


def params(rules=None) -> dict:
    if rules is None:
        try:
            from desk.rules import load_rules; rules = load_rules()
        except Exception:
            rules = None
    p = getattr(rules, "p", rules) or {}
    return {k: type(v)(p.get(k, v)) for k, v in DEFAULTS.items()}


def ceiling(rules=None, env=None) -> float:
    env = os.environ if env is None else env
    v = env.get("BOT_TARGET_BALANCE")
    try: return float(v) if v not in (None, "") else float(params(rules)["target_balance"])
    except ValueError: return 0.0


def reset_balance(rules=None) -> float: return float(params(rules)["reset_balance"])


def ceiling_text(eq, ceil, reset, paper=True):
    pre = "SIMULADO · " if paper else ""
    act = ("(paper: nenhum dinheiro real) — corre o rebase para voltar a $%s" % f"{reset:g}") if paper else \
          "levanta o excedente na app Revolut (o bot nunca levanta) e depois corre o rebase"
    return (f"{pre}teto atingido, sacar e deixar o saldo inicial: equity ${eq:,.2f} ≥ teto ${ceil:,.0f}. "
            f"Operação PAUSADA (sem novas entradas) até rebase manual para ${reset:g} ≈ £50 {act}.")


# ---------------- registo de execuções (erros de API / dados) ----------------
def record_run(h: dict, ts: int, ok: bool, err: str | None = None) -> dict:
    """h: dict persistido pelo chamador. ok = a execução conseguiu dados públicos da Revolut X."""
    h.setdefault("runs", []).append([int(ts), bool(ok)]); h["runs"] = h["runs"][-RUNS_KEEP:]
    if ok:
        h["last_data_ok_ts"] = int(ts); h["fail_streak"] = 0; h["fail_since"] = None
    else:
        h["fail_streak"] = int(h.get("fail_streak") or 0) + 1
        if not h.get("fail_since"): h["fail_since"] = int(ts)
        h["last_error"] = f"{store.iso(ts)} {err or ''}".strip()
    h.setdefault("first_ts", int(ts))
    return h


def api_eval(h: dict, now: int, p: dict) -> dict:
    streak = int(h.get("fail_streak") or 0); since = h.get("fail_since")
    hours = (now - since) / H if (streak and since) else 0.0
    win = [ok for t, ok in h.get("runs", []) if t >= now - p["kill_api_rate_days"] * D]
    rate = (win.count(False) / len(win)) if win else 0.0
    trip_streak = streak >= p["kill_api_fail_min_runs"] and hours >= p["kill_api_fail_hours"]
    trip_rate = len(win) >= p["kill_api_rate_min_runs"] and rate >= p["kill_api_rate_max"]
    return {"value": f"streak {streak} runs / {hours:.1f}h; fail rate {rate:.0%} of {len(win)} runs ({p['kill_api_rate_days']}d)",
            "limit": f"streak ≥{p['kill_api_fail_min_runs']} runs AND ≥{p['kill_api_fail_hours']}h, or rate ≥{p['kill_api_rate_max']:.0%} "
                     f"with ≥{p['kill_api_rate_min_runs']} runs", "tripped": bool(trip_streak or trip_rate),
            "why": "API_ERRORS_STREAK" if trip_streak else ("API_ERROR_RATE" if trip_rate else None)}


def stale_eval(last_ok_ts, first_ts, now, p) -> dict:
    ref = last_ok_ts or first_ts
    days = (now - ref) / D if ref else None
    return {"value": "never ok" if not last_ok_ts else f"{days:.2f} d since last good Revolut X data",
            "limit": f"> {p['kill_data_stale_days']} d", "tripped": days is not None and days > p["kill_data_stale_days"]}


# ---------------- métricas sobre equity ----------------
def daily_last(rows):
    """[(ts_ms, equity)] → [(dia, equity)] com o último valor de cada dia UTC."""
    out = {}
    for t, e in sorted(rows): out[datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")] = e
    return sorted(out.items())


def sharpe_eval(daily_eq: list, p: dict) -> dict:
    n = p["kill_sharpe_days"]
    if len(daily_eq) <= n:
        return {"value": f"INSUFFICIENT_DATA ({max(0, len(daily_eq) - 1)}/{n} daily returns)", "limit": f"< 0 over {n} d",
                "tripped": False, "measurable": False}
    e = daily_eq[-(n + 1):]; r = [e[i + 1] / e[i] - 1 for i in range(n)]
    m = sum(r) / n; sd = math.sqrt(sum((x - m) ** 2 for x in r) / n)
    s = (m / sd * math.sqrt(365)) if sd > 0 else 0.0
    return {"value": f"{s:+.2f} (annualised)", "limit": f"< 0 over {n} d", "tripped": s < 0, "measurable": True}


def dd_eval(eq, peak, limit, informational=False) -> dict:
    dd = 1 - eq / peak if peak else 0.0
    return {"value": f"{dd:.2%}", "limit": f"> {limit:.0%}" + (" (informational only)" if informational else ""),
            "tripped": dd > limit, "informational": informational}


# ---------------- Bot D: referência = journal paper do desk (mesmos sinais, modelo de fills do desk) ----------------
def desk_paper_return(rules, t0, t1) -> float | None:
    """Retorno % do journal paper do desk (equity base `paper_equity`) entre t0 e t1: PnL realizado dos trades fechados na janela."""
    rows = store.read("journal.csv")
    if not rows: return None
    pnl, exit_ts = {}, {}
    for r in rows:
        if r.get("mode") != "PAPER": continue
        tid = r["trade_id"]; pnl[tid] = pnl.get(tid, 0.0) + float(r.get("amount_usd") or 0)
        if r.get("line") == "EXIT":
            exit_ts[tid] = int(datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
    base = float(rules.p.get("paper_equity", 10000)) + sum(pnl[t] for t, x in exit_ts.items() if x < t0)
    win = sum(pnl[t] for t, x in exit_ts.items() if t0 <= x < t1)
    return win / base if base > 0 else None


def executor_diverge_eval(rules, eq_rows, now, p) -> dict:
    n = p["kill_diverge_days"]; lim = p["kill_diverge_max"]
    lab = f"> {lim * 100:.0f} pp over {n} d (reference: desk paper journal, same signals)"
    if not eq_rows or eq_rows[0][0] > now - n * D:
        have = (now - eq_rows[0][0]) / D if eq_rows else 0
        return {"value": f"INSUFFICIENT_DATA ({have:.1f}/{n} d of executor history)", "limit": lab, "tripped": False, "measurable": False}
    t0 = now - n * D
    e0 = [e for t, e in eq_rows if t <= t0][-1]; e1 = eq_rows[-1][1]
    ref = desk_paper_return(rules, t0, now)
    if ref is None: return {"value": "INSUFFICIENT_DATA (no desk paper journal)", "limit": lab, "tripped": False, "measurable": False}
    d = (e1 / e0 - 1) - ref
    return {"value": f"{d * 100:+.2f} pp (exec {(e1 / e0 - 1):+.2%} vs desk {ref:+.2%})", "limit": lab, "tripped": abs(d) > lim,
            "measurable": True}


def read_equity_log(path):
    if not os.path.exists(path): return []
    return [(int(r["ts_ms"]), float(r["equity"])) for r in csv.DictReader(open(path, newline=""))]


# ---------------- relatório ----------------
def report(now=None) -> dict:
    now = now or store.now_ms(); p = params(); ceil = ceiling(); out = {"now": store.iso(now), "ceiling": ceil,
                                                                        "reset_balance": p["reset_balance"], "bots": {}}
    try:
        from desk.rules import load_rules; rules = load_rules(); mode = str(rules.p.get("execution_mode", "off"))
    except Exception as e:
        rules, mode = None, f"error {e}"
    out["execution_mode"] = mode
    # --- Bot D ---
    if mode in ("paper_autonomous", "live"):
        d = store.path(f"exec_{mode}"); sp = os.path.join(d, "state.json")
        st = json.load(open(sp)) if os.path.exists(sp) else {}
        hp = os.path.join(d, "health.json"); h = json.load(open(hp)) if os.path.exists(hp) else {}
        km = st.get("kill_metrics") or {}
        eq = (km.get("equity") if km else None)
        if eq is None and mode == "paper_autonomous":
            px = os.path.join(d, "paper_exchange.json")
            if os.path.exists(px):
                b = json.load(open(px))["bal"]; eq = b.get("USD", 0.0) if len(b) == 1 else None
        crit = dict(km.get("criteria") or {})
        crit["data_stale"] = stale_eval(h.get("last_data_ok_ts"), h.get("first_ts"), now, p)
        crit["api_errors"] = api_eval(h, now, p)
        out["bots"]["D_executor"] = {"mode": mode, "paper": mode != "live", "equity": eq, "peak": st.get("peak"),
                                     "ceiling_distance": (ceil - eq) if eq is not None else None,
                                     "ceiling_latched": st.get("target_latched"), "kill_latched": st.get("kill_latched"),
                                     "global_KILL_file": os.path.exists(store.path("KILL")),
                                     "state": "KILLED" if st.get("kill_latched") else ("PAUSED_CEILING" if st.get("target_latched") else "RUNNING"),
                                     "criteria": crit, "last_run": h.get("last_run")}
    # --- Bots A/B ---
    try:
        from desk.shadow import c3 as C
        cs = C.load_state()
        h = cs.get("health") or {}
        for k, b in cs["books"].items():
            km = (cs.get("kill_metrics") or {}).get(k, {})
            crit = dict(km)
            crit["data_stale"] = stale_eval(h.get("last_data_ok_ts"), h.get("first_ts"), now, p)
            crit["api_errors"] = api_eval(h, now, p)
            if k == "bh_btc":
                for c in crit.values(): c["informational"] = True
            eq = b.get("mark", b["equity"])
            paused = cs.get("paused") or b.get("paused")
            out["bots"][f"{'B' if k == 'bh_btc' else 'A'}_{k}"] = {
                "mode": "shadow paper (c3_unvalidated)", "paper": True, "equity": eq, "equity_close": b["equity"], "peak": b["peak"],
                "ceiling_distance": ceil - eq, "ceiling_latched": b.get("ceiling"), "paused": paused,
                "state": ("PAUSED" if paused else "RUNNING") + (" (baseline: flags only, keeps running)" if k == "bh_btc" else ""),
                "criteria": crit, "last_run": cs.get("last_run")}
    except Exception as e:
        out["bots"]["A/B_c3"] = {"error": f"{type(e).__name__}: {e}"}
    # --- Bots Scalp (paper only; secção separada, só leitura — não entra em "bots" nem em nenhuma regra de kill do desk) ---
    try:
        out["scalp"] = scalp_report(now)
    except Exception as e:
        out["scalp"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def scalp_report(now):
    """Só leitura do estado forward dos bots Scalp (desk/state/scalp_paper/forward). Nunca escreve nem arranca nada."""
    from desk.scalp import run as SR
    s = SR.status(); f = s["forward"]; h = f.get("health") or {}
    stale = f.get("lag_s") is not None and f["lag_s"] > 600
    return {"spec_id": s["spec_id"], "paper_only": True, "loop_running": f["loop_running"], "pid": f["pid"], "started": f["started"],
            "last_bar": f["last_bar"], "lag_s": f["lag_s"], "data_stale_10min": stale, "consec_api_fail": h.get("consec_fail"),
            "last_error": h.get("last_error"), "books": {b: {k: m.get(k) for k in ("name", "state", "equity", "trades", "win_rate",
                                                                                        "expectancy_r", "max_dd", "verdict")}
                                                         for b, m in (f.get("books") or {}).items()}}


def _fmt(rep):
    L = [f"health @ {rep['now']} · execution_mode={rep['execution_mode']} · ceiling ${rep['ceiling']:,.0f} · reset ${rep['reset_balance']:g} (≈£50)"]
    for name, b in rep["bots"].items():
        if "error" in b: L.append(f"\n[{name}] ERROR {b['error']}"); continue
        eq = b.get("equity"); dist = b.get("ceiling_distance")
        L.append(f"\n[{name}] {b['state']} · equity {('$%.2f' % eq) if eq is not None else '?'} · "
                 f"to ceiling {('$%.2f' % dist) if dist is not None else '?'} · last run {b.get('last_run')}")
        for c, v in b["criteria"].items():
            if not isinstance(v, dict): continue
            on = "TRIPPED" if v.get("tripped") else "ok"
            L.append(f"   {c:<14} {on:<8} {v.get('value')}  | limit {v.get('limit')}" + ("  [info]" if v.get("informational") else ""))
    sc = rep.get("scalp")
    if sc:
        if "error" in sc: L.append(f"\n[Scalp] ERROR {sc['error']}")
        else:
            L.append(f"\n[Scalp {sc['spec_id']} · PAPER] loop {'RUNNING pid ' + str(sc['pid']) if sc['loop_running'] else 'STOPPED'} · "
                     f"last bar {sc['last_bar']} (lag {sc['lag_s']} s){' · DATA STALE' if sc['data_stale_10min'] else ''} · "
                     f"api fails seguidas {sc['consec_api_fail']}")
            for b, m in sc["books"].items():
                L.append(f"   {b:<11} {m['state']:<18} equity ${(m['equity'] or 0):.2f} · n={m['trades']} · {m['verdict']}")
    return "\n".join(L)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv); rep = report()
    print(json.dumps(rep, indent=1, ensure_ascii=False, default=str) if "--json" in argv else _fmt(rep))


if __name__ == "__main__":
    main()
