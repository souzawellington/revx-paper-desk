"""Papel 3 — RISK OFFICER. Nunca olha para gráficos: só matemática.
Para cada zona CONFIRMED: tamanho = min(risco % do equity, quarter-Kelly do ledger se disponível, teto 15%).
Adds (+0.5%) só se a entrada anterior na moeda estiver em breakeven. Saída: trade_plan.csv. Pára no plano."""
from __future__ import annotations
import os
from .rules import load_rules, run_tag
import json
from . import logic as L, store
from .roles import guard as guard_mod
from . import panel as PANEL
from . import protections as PROT
from . import macro as MACRO
from . import allocation as ALLOC



def load_skipped_stats():
    p = store.path("skipped_stats.json")
    if not os.path.exists(p): return {}
    try: return json.load(open(p))
    except Exception: return {}


def coin_skipped_bad(coin, rules) -> str | None:
    """Downrank: se expectancy hipotética SKIPPED < limiar com n suficiente → rejeitar."""
    st = load_skipped_stats().get("by_coin", {}).get(coin)
    if not st: return None
    n = st.get("n", 0); ev = st.get("expectancy_r", 0.0)
    if n >= int(rules.skipped_downrank_min_n) and ev <= float(rules.skipped_downrank_max_ev):
        return f"SKIPPED_DOWNRANK:n={n} ev={ev:.3f}R<= {rules.skipped_downrank_max_ev}"
    return None

def equity(rules, log=print):
    """(equity, fonte). Saldo read-only Revolut X se houver credenciais; paper se saldo < min_live_equity."""
    key = os.environ.get("REVX_API_KEY")
    pem = os.environ.get("REVX_PRIVATE_KEY_PATH") or os.path.expanduser("~/.revx-keys/private.pem")
    if key and os.path.exists(pem):
        try:
            from bot.revolutx import RevolutXClient, load_private_key
            from bot.dashboard import ReadOnlyClient
            c = ReadOnlyClient(RevolutXClient(key, load_private_key(open(pem, "rb").read())))
            bals = c.balances(); q = rules.quote; eq = 0.0
            nonq = [b for b in bals if b["currency"] != q and float(b["total"]) > 0]
            px = {}
            if nonq:
                for t in c.public_tickers([f"{b['currency']}-{q}" for b in nonq]):
                    px.setdefault(t["symbol"].split("/")[0], float(t["mid"]))
            for b in bals:
                tot = float(b["total"]); eq += tot if b["currency"] == q else tot * px.get(b["currency"], 0.0)
            if eq >= rules.min_live_equity: return eq, "revolutx_readonly"
            log(f"risk_officer: saldo real {eq:.2f} {q} < {rules.min_live_equity} -> equity paper")
        except Exception as e:
            log(f"risk_officer: saldo read-only indisponível ({type(e).__name__}) -> equity paper")
    realized = sum(store.f(r["amount_usd"], 0) for r in store.read("journal.csv") if r["line"] == "RESULT" and r["mode"] == "PAPER")
    return rules.paper_equity + realized, "paper"


def quarter_kelly(coin, rules):
    if not rules.p.get("use_kelly_ledger", True): return None
    try:
        from bot.config import Config
        from bot.data import SignalStatsStore
        h = SignalStatsStore(Config(quote_currency=rules.quote)).get(coin)
        b = h.avg_win / h.avg_loss; p = h.wins / h.n
        return max(0.0, (b * p - (1 - p)) / b) / 4 * (1 - h.alpha)
    except Exception:
        return None   # ledger ausente/antigo/n<30 -> não disponível


def protection_reasons(coin, positions, eq, rules, now, client=None, log=print):
    """Protections + filtros de pares (desk/protections.py). Só veta. Falha de dados -> filtros INSUFFICIENT_DATA."""
    from . import market
    lk = PROT.locks(PROT.closed_from_positions(positions, rules), now, eq, rules)
    try: d1 = market.candles(coin, 1440, 60, now, client)
    except Exception as e:
        log(f"risk_officer: filtros sem velas para {coin} ({type(e).__name__})"); d1 = None
    tk = None
    try:
        t = (client or market.pub()).public_tickers([coin]); tk = t[0] if t else None
    except Exception: tk = None
    if d1 is None:
        fr = {"reasons": [], "checks": {"age_days": "INSUFFICIENT_DATA", "median_quote_vol": "INSUFFICIENT_DATA",
                                        "daily_vol": "INSUFFICIENT_DATA", "spread": "INSUFFICIENT_DATA"}}
    else:
        fr = PROT.pair_filters(d1, rules, tk)
    reasons = PROT.blocked(coin, lk) + fr["reasons"]
    if rules.p.get("xvenue_check", True):
        xv = xvenue(coin, tk, rules, log)
        fr["checks"]["xvenue"] = xv
        if xv["status"] == "DEVIATION": reasons.append(f"XVENUE_DEVIATION:{xv['dev']:+.2%}")
    return {"mode": PROT.mode(rules), "reasons": reasons, "checks": fr["checks"]}


def xvenue(coin, tk, rules, log=print):
    """Sanity cross-venue (CCXT público, opcional). Sem ccxt/rede/ticker -> INSUFFICIENT_DATA (sem efeito)."""
    try:
        rx = float(tk.get("mid") or tk.get("last_price")) if tk else None
    except (TypeError, ValueError):
        rx = None
    try:
        from . import ccxt_data
        venues = tuple(v.strip() for v in str(rules.p.get("xvenue_venues", "coinbase,kraken,bitstamp")).split(",") if v.strip())
        return ccxt_data.live_sanity(coin, rx, venues, float(rules.p.get("xvenue_max_dev", 0.02)))
    except Exception as e:
        log(f"risk_officer: xvenue indisponível ({type(e).__name__})")
        return {"status": "INSUFFICIENT_DATA", "dev": None, "median": None, "venues": 0}


def panel_decision(coin, positions, rules, now, client=None, log=print):
    """Painel de analistas (desk/panel.py) sobre velas FECHADAS públicas. Falha de dados -> None (sem efeito)."""
    from . import market
    try:
        h4 = market.candles(coin, 240, 150, now, client); d1 = market.candles(coin, 1440, 150, now, client)
        btc = f"BTC-{rules.quote}"
        b1 = d1 if coin == btc else market.candles(btc, 1440, 150, now, client)
        others = sorted({p["coin"] for p in positions if p.get("status") == "OPEN" and p["coin"] != coin})
        od = [market.candles(o, 1440, 90, now, client) for o in others]
        return PANEL.evaluate(rules, h4, d1, b1, od)
    except Exception as e:
        log(f"risk_officer: painel sem dados para {coin} ({type(e).__name__}) -> INSUFFICIENT_DATA, sem efeito")
        return None


def alloc_decision(coin, positions, rules, now, client=None, log=print):
    """HRP (desk/allocation.py) sobre velas 1D FECHADAS públicas do candidato e das posições abertas. Falha -> None."""
    from . import market
    try:
        others = sorted({p["coin"] for p in positions if p.get("status") == "OPEN" and p["coin"] != coin})
        if not others: return ALLOC.decision(coin, [], {}, rules)
        n = int(rules.p.get("alloc_lookback_days", 90)) + 1
        return ALLOC.decision(coin, market.candles(coin, 1440, n, now, client),
                              {o: market.candles(o, 1440, n, now, client) for o in others}, rules)
    except Exception as e:
        log(f"risk_officer: HRP sem dados para {coin} ({type(e).__name__}) -> INSUFFICIENT_DATA, sem efeito")
        return None


def run(rules=None, now=None, log=print, client=None):
    rules = rules or load_rules(); now = now or store.now_ms()
    g = guard_mod.check(rules, now, log=lambda *a: None)
    if g["killed"] or any(r.startswith("DAILY_LOSS_HALT") or r.startswith("MAX_OPEN") for r in g["reasons"]):
        log(f"risk_officer: bloqueado ({';'.join(g['reasons'])})")
        store.append("plan_rejections.csv", [{"ts": store.iso(now), "coin": "*", "zone_id": "*",
                                              "reason": "GUARD_VETO:" + ";".join(g["reasons"])}])
        return []
    zones = store.read("zones.csv"); plans = store.read("trade_plan.csv"); positions = store.read("positions.csv")
    watch = {w["coin"]: w for w in store.read("watchlist.csv")}
    planned = {p["zone_id"] for p in plans}
    eq, src = None, None
    new, rej = [], []
    for z in zones:
        if z["status"] != "CONFIRMED" or z["zone_id"] in planned: continue
        coin = z["coin"]
        if z.get("confirm_ts") and now - int(float(z["confirm_ts"])) > rules.max_alert_age_hours * L.H:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                        "reason": f"confirmação antiga ({store.iso(int(float(z['confirm_ts'])))}; catch-up) — não alertada"})
            z["status"] = "EXPIRED"; continue
        # Texto 1 / no-hero: rejeitar sinais fracos (WATCH) ou não confirmados (já filtrados)
        tag = (watch.get(coin) or {}).get("tag", "")
        if rules.no_hero and tag != "PRIME":
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                        "reason": f"NO_HERO_WEAK: tag={tag or 'MISSING'} (só PRIME+CONFIRMED)"}); z["status"] = "USED"; continue
        open_p = [p for p in positions if p["coin"] == coin and p["status"] == "OPEN"]
        pend = [p for p in plans + new if p["coin"] == coin and p["plan_id"] not in {x["plan_id"] for x in positions}]
        add = len(open_p) + len(pend)
        if add:
            if add > rules.max_adds:
                rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": f"max_adds={rules.max_adds}"}); z["status"] = "USED"; continue
            if pend or not all(p["at_be"] == "True" for p in open_p):
                rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": "entrada anterior não está em breakeven"}); z["status"] = "USED"; continue
        if eq is None: eq, src = equity(rules, log)
        risk = rules.add_risk_pct if add else rules.risk_pct
        if risk > rules.risk_pct and add == 0:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": "NO_HERO: risk_pct acima do trancado"}); continue
        entry, stop = float(z["entry"]), float(z["stop"])
        try:
            tp = L.tp_price(entry, stop, rules.take_profit_r)
        except ValueError as e:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": f"tp inválido: {e}"}); continue
        bad = coin_skipped_bad(coin, rules)
        if bad:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": bad}); z["status"] = "USED"; continue
        if rules.p.get("cost_gate", True):
            ev = L.expected_ev_r_for_plan(entry, stop, rules.take_profit_r, rules)
            if ev <= 0:
                rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                            "reason": f"COST_EV_NONPOSITIVE:ev={ev:.4f}R"}); z["status"] = "USED"; continue
        qty, info = L.size_trade(eq, entry, stop, risk, rules, quarter_kelly(coin, rules))
        notional = qty * entry if qty > 0 else 0.0
        # CAP_EXCEEDED: plano exigiria ultrapassar tetos (spot leverage=1 ou 15%)
        if qty <= 0:
            why = info.get("why", "size 0")
            if "cap" in why.lower() or why == "stop>=entry":
                why = f"CAP_EXCEEDED: {why}"
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"], "reason": why}); continue
        if notional > eq * float(rules.max_leverage_equivalent) + 1e-9:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                        "reason": f"CAP_EXCEEDED: notional {notional:.2f} > equity×{rules.max_leverage_equivalent} ({eq:.2f})"}); continue
        if notional > eq * rules.max_position_frac + 1e-6:
            rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                        "reason": f"CAP_EXCEEDED: notional {notional:.2f} > {rules.max_position_frac:.0%} equity"}); continue
        prot = None
        if PROT.mode(rules) != "off":
            prot = protection_reasons(coin, positions, eq, rules, now, client, log)
            if PROT.mode(rules) == "enforce" and prot["reasons"]:
                rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                            "reason": "PROT_VETO:" + ";".join(prot["reasons"])}); z["status"] = "USED"; continue
        mdec = None
        if MACRO.mode(rules) != "off":
            mdec = MACRO.live_decision(rules, now, log=log)   # cache data_ext/macro; falha -> None/INSUFFICIENT_DATA
            if mdec is not None and MACRO.mode(rules) == "enforce" and mdec["action"] == "VETO":
                rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                            "reason": "MACRO_VETO:" + ",".join(mdec["flags"])}); z["status"] = "USED"; continue
        pdec, binding = None, info["binding"]
        if rules.p.get("panel_mode", "shadow") != "off":
            pdec = panel_decision(coin, positions, rules, now, client, log)
            if pdec is not None:
                if rules.p.get("panel_mode") == "enforce" and pdec["action"] == "VETO":
                    rej.append({"ts": store.iso(now), "coin": coin, "zone_id": z["zone_id"],
                                "reason": f"PANEL_VETO:score={pdec['score']:+.2f}"}); z["status"] = "USED"; continue
                q2, note = PANEL.apply(qty, entry, eq, pdec, rules)
                assert q2 <= qty + 1e-12   # o painel nunca aumenta
                if q2 < qty: qty, notional, binding = q2, q2 * entry, note
        adec = None
        if ALLOC.mode(rules) != "off":
            adec = alloc_decision(coin, positions, rules, now, client, log)
            if adec is not None:
                q3 = ALLOC.apply(qty, entry, eq, adec, rules)
                assert q3 <= qty + 1e-12   # HRP nunca aumenta
                if q3 < qty: qty, notional, binding = q3, q3 * entry, "hrp_cap"
        new.append({"plan_id": f"P-{z['zone_id'].replace(':', '-')}", "coin": coin, "zone_id": z["zone_id"], "entry": entry, "stop": stop,
                    "tp_price": round(tp, 10), "size": round(qty, 8), "notional": round(notional, 2), "risk_pct": risk, "add_number": add,
                    "anchor_low": z["anchor_low"], "created_ts": z["confirm_ts"] or now, "equity": round(eq, 2), "equity_source": src,
                    "sizing_binding": binding, "panel": json.dumps(pdec, separators=(",", ":")) if pdec else "",
                    "prot": json.dumps(prot, separators=(",", ":"), default=str) if prot else "",
                    "macro": json.dumps(mdec, separators=(",", ":"), default=str) if mdec else "",
                    "alloc": json.dumps(adec, separators=(",", ":"), default=str) if adec else "",
                    "tag": run_tag(rules)})   # "paper_fast" = plano gerado no ensaio acelerado (o auditor separa-os)
        z["status"] = "USED"
    store.append("trade_plan.csv", new); store.append("plan_rejections.csv", rej)
    if new or rej: store.write("zones.csv", zones)
    log(f"risk_officer: {len(new)} planos novos, {len(rej)} rejeitados")
    return new


def main(): run()


if __name__ == "__main__":
    main()
