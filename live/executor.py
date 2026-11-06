"""Executor AUTÓNOMO (desligado por defeito). Transforma planos aprovados (desk/state/trade_plan.csv) em ordens.

Modos (DESK_RULES `execution_mode`): off (defeito: não faz nada) | paper_autonomous (mesmo loop contra o PaperBroker) | live.
Em modo autónomo não há TAKEN/SKIPPED: os alertas passam a ser NOTIFICAÇÕES do que o bot fez (outbox, tipo EXEC_*).

Fluxo de cada `run_once` (idempotente; pode correr de hora a hora ou em loop):
 1. off → sai.  KILL → cancela as NOSSAS entradas pendentes (stops/TP do broker ficam a proteger) e sai.
 2. Gates duros (só live): frase BOT_LIVE_CONFIRM, atestação da chave, verificação estrutural sem levantamentos,
    último relatório do auditor = GO (e stats actuais GO), target_balance definido.
 3. Reconciliação: saldos reais + ordens activas + estado de cada ordem nossa (por venue id / client_order_id).
 4. Equity, pico, drawdown (REDUCE 15% → risco ×0.5; SUSPEND 30% trancado), halt diário 3%, target_balance.
 5. Gestão das posições (protecção primeiro): stop do broker (tpsl) para toda a quantidade cheia, BE/trailing −8%
    por cancel/replace, saída por fecho 1D abaixo da âncora, TTL/void das entradas.
 6. Entradas novas (se todos os gates passam): limit post_only ≤ bid, tamanho = min(1% risco, ¼-Kelly, 15%, cash).
Nunca: short, alavancagem, vender holdings que não são do bot, cancel-all, levantamentos/transferências.
"""
from __future__ import annotations
import argparse, csv, glob, json, os, re, time, uuid
from datetime import datetime, timezone
from desk.rules import load_rules, eff, paper_fast_active, PAPER_FAST_TAG
from desk import store, logic as L, health as HL
from desk.roles import guard as guard_mod
from .brokers import LiveBroker, PaperBroker, q_floor, q_ceil, FORBIDDEN_WORDS

H, D = 3_600_000, 86_400_000
NS = uuid.UUID("6f1d3c2e-8a4b-4c1d-9e2f-0a1b2c3d4e5f")
MODES = ("off", "paper_autonomous", "live")


def P(rules, k, d):
    return rules.p.get(k, d)


def coid(mode, plan_id, purpose, seq=0) -> str:
    """client_order_id determinístico (UUID v5): o mesmo plano/propósito/sequência dá SEMPRE o mesmo id."""
    return str(uuid.uuid5(NS, f"{mode}:{plan_id}:{purpose}:{seq}"))


def day_of(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def state_dir(mode): return store.path(f"exec_{mode}")


def target_balance(rules, env) -> float:
    v = env.get("BOT_TARGET_BALANCE")
    try: return float(v) if v not in (None, "") else float(P(rules, "target_balance", 0) or 0)
    except ValueError: return 0.0


# ---------------- gates ----------------
def latest_auditor_go(rules, now) -> tuple[bool, str]:
    """GO só se o relatório semanal MAIS RECENTE disser GO (≤ exec_go_max_age_days) E as stats actuais também."""
    files = sorted(glob.glob(os.path.join(store.STATE, "reports", "weekly_*.md")))
    if not files: return False, "sem relatório do auditor"
    f = files[-1]; txt = open(f, encoding="utf-8").read()
    m = re.search(r"weekly_(\d{4}-\d{2}-\d{2})\.md$", f)
    age = (now - int(datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)) / D
    if age > float(P(rules, "exec_go_max_age_days", 8)): return False, f"relatório do auditor antigo ({age:.0f} d)"
    if "Veredito: GO" not in txt: return False, f"último relatório ({os.path.basename(f)}) = NO-GO"
    from desk.auditor import stats
    if not stats(rules)["go"]: return False, "stats actuais do auditor já não passam (NO-GO)"
    return True, os.path.basename(f)


def structural_safety_check(broker) -> tuple[bool, str]:
    """A API Revolut X não tem endpoints de levantamento; garantir que nem o cliente nem o broker expõem nada parecido
    e que a whitelist de caminhos está activa."""
    from .brokers import path_allowed
    objs = [broker] + ([broker.c] if hasattr(broker, "c") else [])
    for o in objs:
        bad = [n for n in dir(o) if any(w in n.lower() for w in FORBIDDEN_WORDS)]
        if bad: return False, f"métodos proibidos expostos: {bad}"
    probes = [(m, f"/api/1.0/{w}s") for w in FORBIDDEN_WORDS for m in ("GET", "POST", "DELETE")] + [("DELETE", "/api/1.0/orders")]
    for m, pth in probes:
        if path_allowed(m, pth): return False, f"whitelist deixaria passar {m} {pth}"
    return True, "ok (API sem endpoints de levantamento; whitelist activa; permissões da chave não são legíveis pela API)"


def hard_gates(mode, rules, env, broker, now) -> list[str]:
    fails = []
    ok, why = structural_safety_check(broker)
    if not ok: fails.append("NO_WITHDRAW_CHECK:" + why)
    if mode != "live": return fails
    if env.get("BOT_LIVE_CONFIRM", "") != str(P(rules, "live_confirm_phrase", "")) or not P(rules, "live_confirm_phrase", ""):
        fails.append("BOT_LIVE_CONFIRM ausente ou diferente da frase em DESK_RULES")
    if env.get("BOT_KEY_ATTESTED", "") != "trade_only_no_withdraw":
        fails.append("BOT_KEY_ATTESTED≠trade_only_no_withdraw (atestação da chave)")
    if target_balance(rules, env) <= 0: fails.append("target_balance não definido")
    go, why = latest_auditor_go(rules, now)
    if not go: fails.append("AUDITOR_NOT_GO:" + why)
    return fails


# ---------------- executor ----------------
class Executor:
    def __init__(self, rules=None, mode=None, broker=None, env=None, now=None, log=print):
        self.rules = rules or load_rules(); self.mode = mode or str(P(self.rules, "execution_mode", "off"))
        if self.mode not in MODES: raise ValueError(f"execution_mode inválido: {self.mode}")
        self.env = os.environ if env is None else env; self.now = now or store.now_ms(); self.log = log
        self.broker = broker; self.dir = state_dir(self.mode); self.sp = os.path.join(self.dir, "state.json")
        self.st = json.load(open(self.sp)) if os.path.exists(self.sp) else {
            "enabled_ts": self.now, "positions": {}, "handled": [], "peak": None, "suspended": False,
            "day": None, "day_start": None, "orders_day": {}, "target_latched": None, "kill_latched": None}
        self.st.setdefault("kill_latched", None)
        self.notes = []

    # ---- util ----
    def save(self):
        os.makedirs(self.dir, exist_ok=True); tmp = self.sp + ".tmp"
        json.dump(self.st, open(tmp, "w"), indent=1, default=str); os.replace(tmp, self.sp)

    def notify(self, kind, key, text, data=None):
        a = {"id": f"EXEC:{self.mode}:{kind}:{key}", "type": f"EXEC_{kind}", "mode": self.mode, "text": f"🤖 [{self.mode}] {text}",
             "data": data or {}, "reply_options": []}
        if store.emit(a): self.notes.append(a)
        self.log(f"executor: {kind} {text}")

    def journal(self, row):
        p = os.path.join(self.dir, "exec_journal.csv"); new = not os.path.exists(p); os.makedirs(self.dir, exist_ok=True)
        cols = ["ts", "mode", "pid", "symbol", "event", "qty", "price", "r", "note", "tag"]
        if not new:   # migração: journal antigo sem a coluna tag
            with open(p, newline="") as fh: hdr = next(csv.reader(fh), [])
            if hdr != cols:
                with open(p, newline="") as fh: old = list(csv.DictReader(fh))
                with open(p, "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
                    for o in old: w.writerow({k: o.get(k, "") for k in cols})
        tag = row.pop("tag", None)
        if tag is None: tag = (self.st["positions"].get(row.get("pid")) or {}).get("tag", "")
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new: w.writeheader()
            w.writerow({"ts": store.iso(self.now), "mode": self.mode, **row, "tag": tag or ""})

    def fast(self) -> bool:
        """Ensaio acelerado: SÓ em paper_autonomous com PaperBroker; nunca em live/off (mesmo que o bloco exista)."""
        return self.mode == "paper_autonomous" and paper_fast_active(self.rules) and isinstance(self.broker, PaperBroker)

    def max_open(self) -> int:
        return int(eff(self.rules, "max_open_positions")) if self.fast() else int(self.rules.max_open_positions)

    def orders_today(self): return self.st["orders_day"].get(day_of(self.now), 0)

    def can_order(self, protective=False):
        cap = int(P(self.rules, "exec_max_orders_day", 900))
        return self.orders_today() < (min(990, cap + 90) if protective else cap)

    def count_order(self): d = day_of(self.now); self.st["orders_day"] = {d: self.orders_today() + 1}

    def place(self, fn, *a, protective=False, **k):
        """Coloca uma ordem respeitando o tecto diário; erros não levantam (registados, retentados no próximo ciclo)."""
        if not self.can_order(protective): self.notify("ORDER_CAP", day_of(self.now), "tecto diário de ordens atingido"); return None
        try:
            r = fn(*a, **k); self.count_order(); return r
        except PermissionError: raise
        except Exception as e:
            self.log(f"executor: falha a colocar ordem ({type(e).__name__}: {e}) — reconcilia no próximo ciclo"); self.count_order(); return None

    # ---- ciclo ----
    def run_once(self) -> dict:
        if self.mode == "off": return {"ran": False, "why": "execution_mode=off"}
        b = self.broker
        if b is None: raise RuntimeError("broker não configurado")
        if self.st.get("kill_latched"):          # critério de morte disparou antes: KILL trancado até `unkill --confirm`
            self.kill(); self.save(); return {"ran": True, "killed": True, "kill_latched": self.st["kill_latched"], "notes": self.notes}
        if isinstance(b, PaperBroker): b.advance(self.now)
        if guard_mod.is_killed():
            self.kill(); self.save(); return {"ran": True, "killed": True, "notes": self.notes}
        data_ok, derr = self.probe_data()
        h = record_health(self.mode, self.now, data_ok, derr)
        fails = hard_gates(self.mode, self.rules, self.env, b, self.now)
        if fails:
            self.notify("BLOCKED", day_of(self.now) + ":" + str(abs(hash(tuple(fails))) % 10**6), "nenhuma ordem: " + "; ".join(fails))
            self.save(); return {"ran": True, "blocked": fails, "notes": self.notes}
        bals = b.balances(); active = {o["id"]: o for o in b.active_orders()}
        self.reconcile(bals, active)
        eq = self.equity(b.balances())
        gates = self.risk_gates(eq)
        self.log_equity(eq)
        crit = self.kill_criteria(eq, gates, h)
        tripped = [k for k, v in crit.items() if v.get("tripped")]
        if tripped:
            self.auto_kill("; ".join(f"{k}: {crit[k]['value']} (limite {crit[k]['limit']})" for k in tripped))
            self.save(); return {"ran": True, "killed": True, "kill_latched": self.st["kill_latched"], "equity": eq, "notes": self.notes}
        self.manage(gates)
        opened = self.enter(eq, gates) if not gates["block_entries"] else []
        self.save()
        return {"ran": True, "equity": eq, "gates": gates, "opened": opened, "notes": self.notes,
                "positions": {k: v["status"] for k, v in self.st["positions"].items()}}

    # ---- critérios de morte (desk/health.py) ----
    def probe_data(self):
        """1 pedido público (ticker BTC-USD) por execução: prova que há dados frescos da Revolut X."""
        try:
            t = self.broker.ticker(f"BTC-{self.rules.quote}")
            return (bool(t and float(t.get("mid") or t.get("bid") or 0) > 0), None)
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:120]}"

    def log_equity(self, eq):
        p = os.path.join(self.dir, "equity.csv"); new = not os.path.exists(p); os.makedirs(self.dir, exist_ok=True)
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["ts_ms", "ts", "equity"])
            w.writerow([self.now, store.iso(self.now), f"{eq:.6f}"])

    def kill_criteria(self, eq, gates, h) -> dict:
        p = HL.params(self.rules); since = int(self.st.get("since_ts") or 0)
        rows = [x for x in HL.read_equity_log(os.path.join(self.dir, "equity.csv")) if x[0] >= since]
        c = {"forward_dd": HL.dd_eval(eq, self.st.get("peak") or eq, p["kill_dd_max"])}
        if self.st.get("target_latched"):      # no teto o levantamento parece DD: critério suspenso até ao rebase
            c["forward_dd"].update(tripped=False, value=c["forward_dd"]["value"] + " (suspenso: teto trancado)")
        c["sharpe_12m"] = HL.sharpe_eval([e for _, e in HL.daily_last(rows)], p)
        c["divergence"] = HL.executor_diverge_eval(self.rules, rows, self.now, p)
        c["data_stale"] = HL.stale_eval(h.get("last_data_ok_ts"), h.get("first_ts"), self.now, p)
        c["api_errors"] = HL.api_eval(h, self.now, p)
        self.st["kill_metrics"] = {"ts": store.iso(self.now), "equity": eq, "criteria": c}
        return c

    def auto_kill(self, why):
        if not self.st.get("kill_latched"):
            self.st["kill_latched"] = {"reason": why, "at": store.iso(self.now)}
            pre = "SIMULADO · " if self.mode != "live" else ""
            self.notify("KILL_AUTO", day_of(self.now), f"{pre}critério de morte disparou → KILL automático: {why}. "
                        "Sem novas entradas até revisão humana (`python -m live.executor unkill --confirm`).", {"reason": why})
        self.kill()

    # ---- kill ----
    def kill(self):
        action = str(P(self.rules, "exec_kill_action", "cancel_entries"))
        for p in self.st["positions"].values():
            if p["status"] == "PENDING_ENTRY" and p.get("entry_oid"):
                try: self.broker.cancel(p["entry_oid"])
                except Exception as e: self.log(f"executor: cancel falhou {e}")
                o = self._get(p["entry_oid"]); p["filled"] = o["filled"] if o else p.get("filled", 0)
                p["status"] = "OPEN" if p["filled"] > 0 else "CANCELLED"
            if action == "flatten" and p["status"] == "OPEN":
                self.exit_market(p, "KILL_SWITCH")
        self.notify("KILL", day_of(self.now), f"KILL activo: entradas pendentes canceladas; acção={action}. "
                    + ("Stops/TP do broker continuam a proteger as posições abertas." if action != "flatten" else "Posições fechadas a mercado."))

    # ---- reconciliação ----
    def _get(self, oid):
        try: return self.broker.get_order(oid)
        except Exception as e: self.log(f"executor: get_order falhou ({type(e).__name__})"); return None

    def _find_coid(self, c):
        for o in self.broker.active_orders():
            if o.get("coid") == c: return o
        f = getattr(self.broker, "find_by_coid", None)
        return f(c) if f else None

    def reconcile(self, bals, active):
        for p in self.st["positions"].values():
            if p["status"] in ("CLOSED", "VOID", "CANCELLED"): continue
            # ordens com resultado desconhecido (erro de rede): adoptar pelo client_order_id
            if p["status"] == "PENDING_ENTRY" and not p.get("entry_oid"):
                o = self._find_coid(p["entry_coid"])
                if o: p["entry_oid"] = o["id"]
                else: p["status"] = "CANCELLED"; continue
            if p["status"] == "PENDING_ENTRY":
                o = active.get(p["entry_oid"]) or self._get(p["entry_oid"])
                if o:
                    p["filled"], p["avg_entry"] = o["filled"], o["avg"] or p.get("avg_entry")
                    if o["status"] == "filled": self.on_entry_done(p)
                    elif o["status"] in ("cancelled", "rejected") :
                        if p["filled"] > 0: self.on_entry_done(p)
                        else: p["status"] = "CANCELLED"; self.notify("ENTRY_CANCELLED", p["pid"], f"{p['symbol']}: entrada {o['status']} sem fill")
            if p["status"] == "OPEN":
                if p.get("prot_coid") and not p.get("prot_oid"):
                    o = self._find_coid(p["prot_coid"]); p["prot_oid"] = o["id"] if o else None
                if p.get("prot_oid"):
                    o = active.get(p["prot_oid"]) or self._get(p["prot_oid"])
                    if o and o["status"] == "filled":
                        why = {"stop_loss": "STOP_BROKER", "take_profit": "TAKE_PROFIT_BROKER"}.get(o.get("trigger_reason"), "BROKER_EXIT")
                        self.on_closed(p, o["avg"] or p["prot_stop"], why); continue
                    if o and o["status"] in ("cancelled", "rejected"):
                        p["prot_oid"] = None   # recolocar abaixo (manage)
                # posição fechada por fora (venda manual na app): saldo do activo < quantidade gerida
                base = p["symbol"].split("-")[0]; held = bals.get(base, {}).get("total", 0.0)
                if held < p["qty"] * 0.98:
                    if p.get("prot_oid"):
                        try: self.broker.cancel(p["prot_oid"])
                        except Exception: pass
                    self.on_closed(p, None, "EXTERNAL_CLOSE")

    def on_entry_done(self, p):
        p["status"] = "OPEN"; p["qty"] = p["filled"]; fill = p["avg_entry"] or p["limit"]
        p["entry"] = fill; p["peak"] = fill
        plan_r = p["plan_entry"] - p["plan_stop"]
        p["tp"] = p["plan_tp"] if abs(fill - p["plan_entry"]) < 1e-12 else fill + self.rules.take_profit_r * plan_r
        p["stop"] = max(p["plan_stop"], fill * (1 - self.rules.hard_stop_pct)); p["initial_stop"] = p["plan_stop"]
        p["opened_ts"] = self.now
        self.journal({"pid": p["pid"], "symbol": p["symbol"], "event": "ENTRY", "qty": p["qty"], "price": fill})
        self.notify("ENTRY_FILLED", p["pid"], f"COMPREI {p['qty']:.8g} {p['symbol']} @ {fill:.6g} · stop {p['stop']:.6g} · TP {p['tp']:.6g}")

    def on_closed(self, p, px, why):
        p["status"] = "CLOSED"; p["exit_rule"] = why; p["exit"] = px; p["closed_ts"] = self.now
        r = None
        if px:
            risk = p["entry"] - p["initial_stop"]
            fee = self.rules.taker_fee if why in ("STOP_BROKER", "STOP_MONITOR", "ANCHOR_1D_CLOSE", "KILL_SWITCH") else 0.0
            r = ((px * (1 - fee)) - p["entry"]) / risk if risk > 0 else None
        p["r"] = r
        self.journal({"pid": p["pid"], "symbol": p["symbol"], "event": "EXIT", "qty": p["qty"], "price": px or "", "r": r if r is not None else "", "note": why})
        self.notify("EXIT", p["pid"], f"VENDI {p['symbol']} ({why}) @ {px if px else '?'}" + (f" · {r:+.2f}R" if r is not None else ""))

    # ---- equity e gates de risco ----
    def equity(self, bals):
        q = self.rules.quote; eq = 0.0
        for cur, v in bals.items():
            if v["total"] <= 0: continue
            if cur == q: eq += v["total"]; continue
            try: eq += v["total"] * self.broker.ticker(f"{cur}-{q}")["mid"]
            except Exception: self.log(f"executor: sem preço para {cur} (contado como 0)")
        return eq

    def risk_gates(self, eq):
        st, r = self.st, self.rules; d = day_of(self.now)
        # levantamento detectado com o target trancado → rebase automático (não é drawdown)
        tl = st.get("target_latched")
        if tl and not tl.get("withdrawn") and eq < tl["eq"] * 0.99 and not any(p["status"] in ("OPEN", "PENDING_ENTRY") for p in st["positions"].values()):
            realized = sum(p["qty"] * ((p.get("exit") or p["entry"]) - p["entry"]) for p in st["positions"].values()
                           if p["status"] == "CLOSED" and (p.get("closed_ts") or 0) >= tl["ts"])
            if tl["eq"] + realized - eq > 0.01 * tl["eq"]:
                st["peak"] = eq; st["day_start"] = eq; tl["withdrawn"] = True
                self.notify("REBASED", d, f"levantamento detectado (equity {eq:.2f}); pico/dia reiniciados. Continua PAUSADO no teto "
                            "até `python -m live.executor rebase --confirm`")
        if st["day"] != d: st["day"], st["day_start"] = d, eq
        st["peak"] = max(st["peak"] or eq, eq); dd = 1 - eq / st["peak"] if st["peak"] else 0.0
        if dd >= float(P(r, "exec_dd_suspend", 0.30)): st["suspended"] = True
        mult = 0.0 if st["suspended"] else (float(P(r, "exec_reduce_mult", 0.5)) if dd >= float(P(r, "exec_dd_reduce", 0.15)) else 1.0)
        day_loss = (eq - st["day_start"]) / st["day_start"] if st["day_start"] else 0.0
        halt = day_loss <= -float(r.daily_loss_halt_pct)
        tgt = target_balance(r, self.env)
        if tgt > 0 and eq >= tgt and not st.get("target_latched"):
            st["target_latched"] = {"eq": eq, "ts": self.now, "target": tgt}
            self.notify("TARGET_REACHED", f"{tgt:g}:{self.now}", HL.ceiling_text(eq, tgt, HL.reset_balance(r), paper=self.mode != "live")
                        + (" Comando: python -m live.executor rebase --confirm"), {"equity": eq, "ceiling": tgt})
        # teto TRANCADO: fica pausado mesmo que o saldo desça, até rebase manual (nunca retoma sozinho)
        at_target = bool(st.get("target_latched"))
        reasons = []
        if st["suspended"]: reasons.append(f"DD_SUSPEND:{dd:.1%}")
        if halt: reasons.append(f"DAILY_LOSS_HALT:{day_loss:.1%}")
        if at_target: reasons.append(f"TARGET_BALANCE:{st['target_latched']['eq']:.2f}>={st['target_latched']['target']:g} (trancado até rebase)")
        live_open = sum(1 for p in st["positions"].values() if p["status"] in ("OPEN", "PENDING_ENTRY"))
        if live_open >= self.max_open(): reasons.append(f"MAX_OPEN_POSITIONS:{live_open}")
        if not self.can_order(): reasons.append("ORDER_CAP")
        if reasons and any(x.startswith(("DD_SUSPEND", "DAILY_LOSS", "TARGET")) for x in reasons):
            self.cancel_pending("; ".join(reasons))
        return {"equity": eq, "dd": dd, "risk_mult": mult, "day_loss": day_loss, "target": tgt, "reasons": reasons,
                "block_entries": bool(reasons) or mult == 0.0}

    def cancel_pending(self, why):
        for p in self.st["positions"].values():
            if p["status"] == "PENDING_ENTRY" and p.get("entry_oid") and (p.get("filled") or 0) == 0:
                try: self.broker.cancel(p["entry_oid"])
                except Exception: pass
                p["status"] = "CANCELLED"; self.notify("ENTRY_CANCELLED", p["pid"], f"{p['symbol']}: entrada cancelada ({why})")

    # ---- gestão (protecção primeiro) ----
    def manage(self, gates):
        b, r = self.broker, self.rules
        for p in self.st["positions"].values():
            if p["status"] == "PENDING_ENTRY":
                tk = self._ticker(p["symbol"])
                ttl = float(P(r, "exec_entry_ttl_min", 120)) * 60_000
                if self.now - p["placed_ts"] >= ttl or (tk and tk["bid"] <= p["plan_stop"]):
                    if p.get("entry_oid"):
                        try: b.cancel(p["entry_oid"])
                        except Exception: pass
                        o = self._get(p["entry_oid"])
                        if o: p["filled"], p["avg_entry"] = o["filled"], o["avg"] or p.get("avg_entry")
                    if (p.get("filled") or 0) > 0: self.on_entry_done(p)
                    else:
                        p["status"] = "CANCELLED"; self.notify("ENTRY_CANCELLED", p["pid"], f"{p['symbol']}: entrada expirada/void sem fill")
            if p["status"] != "OPEN": continue
            pos = L.Position(p["pid"], p["symbol"], p["entry"], p["stop"], p["qty"], 0.01, 0, p["anchor_low"], p["opened_ts"],
                             peak=p["peak"], at_be=p.get("at_be", False), initial_stop=p["initial_stop"], tp_price=p["tp"])
            # velas 1H fechadas desde a última verificação → pico/BE (lógica do desk) + hard −8% sobre o pico
            last = p.get("last_h1") or p["opened_ts"]
            try:
                bars = [c for c in b.candles(p["symbol"], 60, last) if c["start"] >= last and c["start"] + H <= self.now]
            except Exception: bars = []
            for c in bars: L.after_bar(pos, c, r); p["last_h1"] = c["start"] + H
            p["peak"], p["at_be"] = pos.peak, pos.at_be
            p["stop"] = max(pos.stop, max(p["entry"], pos.peak) * (1 - r.hard_stop_pct))
            # saída por fecho diário abaixo da âncora
            try:
                d1 = [c for c in b.candles(p["symbol"], 1440, self.now - 3 * D) if c["start"] + D <= self.now and c["start"] + D > p["opened_ts"]]
            except Exception: d1 = []
            if d1 and d1[-1]["close"] < p["anchor_low"]:
                self.exit_market(p, "ANCHOR_1D_CLOSE"); continue
            self.ensure_protection(p)

    def _ticker(self, s):
        try: return self.broker.ticker(s)
        except Exception: return None

    def ensure_protection(self, p):
        """Stop do lado do broker (tpsl). Recoloca se não existe, se a quantidade mudou ou se o stop subiu ≥ exec_stop_replace_min."""
        b, r = self.broker, self.rules; pair = b.pairs().get(p["symbol"], {})
        qs, ps = pair.get("base_step", "0.00000001"), pair.get("quote_step", "0.00000001")
        base = p["symbol"].split("-")[0]
        need = p.get("prot_oid") is None or abs(p.get("prot_qty", 0) - p["qty"]) > 1e-12 or \
            p["stop"] >= (p.get("prot_stop") or 0) * (1 + float(P(r, "exec_stop_replace_min", 0.005)))
        if p.get("stop_mode") == "monitor":
            tk = self._ticker(p["symbol"])
            if tk and tk["bid"] <= p["stop"]: self.exit_market(p, "STOP_MONITOR"); return
        if not need: return
        if p.get("prot_oid"):
            try: b.cancel(p["prot_oid"])
            except Exception: pass
            o = self._get(p["prot_oid"])
            if o and o["filled"] > 0:      # disparou durante o cancel → fechado (parcial ou total)
                why = {"stop_loss": "STOP_BROKER", "take_profit": "TAKE_PROFIT_BROKER"}.get(o.get("trigger_reason"), "BROKER_EXIT")
                if o["filled"] >= p["qty"] - 1e-12: self.on_closed(p, o["avg"], why); return
                p["qty"] -= o["filled"]
            p["prot_oid"] = None
        held = b.balances().get(base, {}).get("available", 0.0)
        qty = min(p["qty"], held); p["prot_seq"] = p.get("prot_seq", 0) + 1
        c = coid(self.mode, p["plan_id"], "tpsl", p["prot_seq"]); p["prot_coid"] = c
        res = self.place(b.tpsl_sell, p["symbol"], q_floor(qty, qs), q_ceil(p["tp"], ps), q_ceil(p["stop"], ps), c, protective=True)
        if res and res.get("id") and res.get("status") not in ("rejected",):
            p.update(prot_oid=res["id"], prot_qty=p["qty"], prot_stop=p["stop"], stop_mode="broker")
        else:
            p["stop_mode"] = "monitor"
            self.notify("STOP_FALLBACK", f"{p['pid']}:{p['prot_seq']}", f"{p['symbol']}: stop do broker NÃO aceite — monitor local "
                        f"(venda a mercado se bid ≤ {p['stop']:.6g}; só tão rápido quanto a cadência do executor)")
            tk = self._ticker(p["symbol"])
            if tk and tk["bid"] <= p["stop"]: self.exit_market(p, "STOP_MONITOR")

    def exit_market(self, p, why):
        b = self.broker
        if p.get("prot_oid"):
            try: b.cancel(p["prot_oid"])
            except Exception: pass
            o = self._get(p["prot_oid"])
            if o and o["filled"] >= p["qty"] - 1e-12: self.on_closed(p, o["avg"], "STOP_BROKER"); return
            p["prot_oid"] = None
        base = p["symbol"].split("-")[0]; qs = b.pairs().get(p["symbol"], {}).get("base_step", "0.00000001")
        qty = min(p["qty"], b.balances().get(base, {}).get("available", 0.0))
        p["exit_seq"] = p.get("exit_seq", 0) + 1
        res = self.place(b.market_sell, p["symbol"], q_floor(qty, qs), coid(self.mode, p["plan_id"], "exit", p["exit_seq"]), protective=True)
        if res and res.get("status") == "filled": self.on_closed(p, res.get("avg"), why)
        elif res and res.get("id"):
            o = self._get(res["id"]); self.on_closed(p, (o or {}).get("avg"), why)
        else:
            self.notify("EXIT_FAILED", f"{p['pid']}:{p['exit_seq']}", f"{p['symbol']}: venda a mercado falhou ({why}) — tento no próximo ciclo")

    # ---- entradas ----
    def enter(self, eq, gates):
        r, b = self.rules, self.broker; opened = []
        handled = set(self.st["handled"])
        n_open = sum(1 for p in self.st["positions"].values() if p["status"] in ("OPEN", "PENDING_ENTRY"))
        for pl in store.read("trade_plan.csv"):
            pid = pl["plan_id"]
            if pid in handled: continue
            created = int(float(pl["created_ts"] or 0))
            handled.add(pid); self.st["handled"].append(pid)
            if created < self.st["enabled_ts"] - H or self.now - created > float(r.max_alert_age_hours) * H:
                continue    # planos antigos (antes de ligar o executor) ou fora de prazo: nunca executar
            if n_open >= self.max_open(): self.notify("SKIP", pid, f"{pl['coin']}: máx. posições"); continue
            sym = pl["coin"]; tk = self._ticker(sym)
            if not tk: self.notify("SKIP", pid, f"{sym}: sem ticker"); continue
            entry, stop, tp = float(pl["entry"]), float(pl["stop"]), float(pl["tp_price"] or L.tp_price(float(pl["entry"]), float(pl["stop"]), r.take_profit_r))
            price = min(tk["bid"], entry * (1 + float(P(r, "exec_entry_tol", 0.002))))
            post_only = True
            # ensaio acelerado: entrada "marketable" (compra ao ask, taker) se o ask ainda está ≤ entrada × (1 + paper_entry_tol);
            # senão cai para o limite post-only normal. Stop/TP/risco do plano NÃO mudam (o tamanho usa o preço real).
            if self.fast() and str(P(r, "paper_entry_mode", "post_only")) == "marketable" and tk.get("ask") \
                    and tk["ask"] * (1 + r.slippage) <= entry * (1 + float(P(r, "paper_entry_tol", 0.01))):
                price, post_only = tk["ask"] * (1 + r.slippage), False   # limite = ask + slippage (preço pessimista)
            if price <= stop or tk["ask"] >= tp:
                self.notify("SKIP", pid, f"{sym}: preço {price:.6g} fora de [stop {stop:.6g}, TP {tp:.6g}]"); continue
            from desk.risk_officer import quarter_kelly
            risk = float(pl["risk_pct"] or r.risk_pct) * gates["risk_mult"]
            risk = min(risk, float(r.risk_pct))
            qty, info = L.size_trade(eq, price, stop, risk, r, quarter_kelly(sym, r))
            cash = b.balances().get(r.quote, {}).get("available", 0.0)
            unit_cost = price if post_only else price * (1 + r.taker_fee)   # taker paga taxa (slippage já no preço)
            qty = min(qty, cash / unit_cost * 0.999, eq * r.max_position_frac / price)   # sem alavancagem; teto 15%
            pair = b.pairs().get(sym, {}); qs, ps = pair.get("base_step", "0.00000001"), pair.get("quote_step", "0.00000001")
            qstr, pstr = q_floor(qty, qs), (q_floor(price, ps) if post_only else q_ceil(price, ps))
            if float(qstr) <= 0 or float(qstr) < float(pair.get("min_order_size", 0)) or float(qstr) * float(pstr) < float(pair.get("min_order_size_quote", 0)):
                self.notify("SKIP", pid, f"{sym}: tamanho abaixo do mínimo ({qstr})"); continue
            c = coid(self.mode, pid, "entry")
            p = {"pid": pid, "plan_id": pid, "symbol": sym, "status": "PENDING_ENTRY", "entry_coid": c, "entry_oid": None,
                 "limit": float(pstr), "qty_target": float(qstr), "filled": 0.0, "avg_entry": None, "plan_entry": entry,
                 "plan_stop": stop, "plan_tp": tp, "anchor_low": float(pl["anchor_low"]), "placed_ts": self.now, "risk": risk,
                 "tag": PAPER_FAST_TAG if self.fast() else (pl.get("tag") or "")}
            self.st["positions"][pid] = p
            res = self.place(b.limit_buy, sym, qstr, pstr, c, post_only)
            if res and res.get("id") and res.get("status") != "rejected":
                p["entry_oid"] = res["id"]; n_open += 1; opened.append(pid)
                self.notify("ENTRY_PLACED", pid, f"ordem de compra {qstr} {sym} @ {pstr} ({'post-only' if post_only else 'marketable/taker'}; risco {risk:.2%}; "
                            f"{info.get('binding')})" + (f" [{p['tag']}]" if p["tag"] else ""))
                if res.get("status") == "filled":
                    p["filled"], p["avg_entry"] = res["filled"], res["avg"]; self.on_entry_done(p); self.ensure_protection(p)
            elif res is None:
                n_open += 1   # resultado desconhecido: o reconcile adopta pelo client_order_id
            else:
                p["status"] = "CANCELLED"; self.notify("SKIP", pid, f"{sym}: ordem rejeitada")
        return opened


# ---------------- saúde (erros de API / dados) ----------------
def health_path(mode): return os.path.join(state_dir(mode), "health.json")


def record_health(mode, now, ok, err=None) -> dict:
    p = health_path(mode); h = json.load(open(p)) if os.path.exists(p) else {}
    HL.record_run(h, now, ok, err); h["last_run"] = store.iso(now)
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".tmp"; json.dump(h, open(tmp, "w"), indent=1); os.replace(tmp, p)
    return h


def on_run_failure(rules, mode, now, err, log=print) -> dict:
    """Execução falhou (ex.: 502 da Revolut X): regista e avalia stale/API; se disparar → KILL trancado (sem rede)."""
    h = record_health(mode, now, False, err); p = HL.params(rules)
    c = {"data_stale": HL.stale_eval(h.get("last_data_ok_ts"), h.get("first_ts"), now, p), "api_errors": HL.api_eval(h, now, p)}
    tripped = [k for k, v in c.items() if v["tripped"]]
    out = {"ran": False, "error": err, "fail_streak": h.get("fail_streak"), "criteria": c}
    if tripped:
        ex = Executor(rules, mode, broker=None, now=now, log=log)
        why = "; ".join(f"{k}: {c[k]['value']}" for k in tripped)
        if not ex.st.get("kill_latched"):
            ex.st["kill_latched"] = {"reason": why, "at": store.iso(now)}
            pre = "SIMULADO · " if mode != "live" else ""
            ex.notify("KILL_AUTO", day_of(now), f"{pre}critério de morte disparou → KILL automático: {why}. Entradas pendentes "
                      "serão canceladas na próxima execução com API; stops do broker mantêm-se. Revisão: `python -m live.executor unkill --confirm`.",
                      {"reason": why})
        ex.save(); out["kill_latched"] = ex.st["kill_latched"]
    return out


def paper_rebase(rules, mode, now=None):
    """Paper: simula o levantamento — o saldo volta a reset_balance (só sem posições/ordens do bot abertas)."""
    reset = HL.reset_balance(rules); px = os.path.join(state_dir(mode), "paper_exchange.json")
    if os.path.exists(px):
        s = json.load(open(px))
        sp = os.path.join(state_dir(mode), "state.json"); st = json.load(open(sp)) if os.path.exists(sp) else {"positions": {}}
        if any(o["status"] in ("new", "partially_filled") for o in s["orders"].values()) or \
                any(p["status"] in ("OPEN", "PENDING_ENTRY") for p in st.get("positions", {}).values()):
            raise SystemExit("rebase paper recusado: ainda há posições/ordens abertas — espera que fechem (stop/TP) e repete")
        before = s["bal"].get(rules.quote, 0.0); s["bal"] = {rules.quote: reset}
        tmp = px + ".tmp"; json.dump(s, open(tmp, "w"), indent=1); os.replace(tmp, px)
        return before, reset
    return None, reset


# ---------------- construção / CLI ----------------
class PublicMarket:
    """Dados PÚBLICOS (sem credenciais) para o PaperBroker."""
    def __init__(self):
        from bot.revolutx import RevolutXClient
        self.c = RevolutXClient(); self._pairs = None

    def ticker(self, s):
        t = self.c.public_tickers([s])[0]; return {k: float(t[k]) for k in ("bid", "ask", "mid", "last_price") if t.get(k) not in (None, "")}

    def pairs(self):
        if self._pairs is None: self._pairs = {k.replace("/", "-"): v for k, v in self.c.public_pairs().items()}
        return self._pairs

    def candles(self, s, interval, since, until=None):
        return [{"start": int(c["start"]), **{k: float(c[k]) for k in ("open", "high", "low", "close", "volume")}}
                for c in self.c.public_candles(s, interval, since=since, until=until)]


def make_broker(mode, rules, env=os.environ, now=None):
    if mode == "paper_autonomous":
        return PaperBroker(os.path.join(state_dir(mode), "paper_exchange.json"), PublicMarket(),
                           cash=float(P(rules, "paper_autonomous_equity", 65)), quote=rules.quote,
                           taker=rules.taker_fee, slippage=rules.slippage, clock=lambda: now or store.now_ms())
    if mode == "live":
        from bot.revolutx import RevolutXClient, load_private_key
        key, pem = env.get("REVX_TRADE_API_KEY"), env.get("REVX_TRADE_PRIVATE_KEY_PATH")
        if not key or not pem or not os.path.exists(pem): raise SystemExit("live: REVX_TRADE_API_KEY / REVX_TRADE_PRIVATE_KEY_PATH em falta")
        return LiveBroker(RevolutXClient(key, load_private_key(open(pem, "rb").read())))
    return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["run-once", "loop", "status", "rebase", "unkill"])
    ap.add_argument("--interval", type=int, default=300); ap.add_argument("--confirm", action="store_true"); a = ap.parse_args()
    rules = load_rules(); mode = str(P(rules, "execution_mode", "off"))
    if a.cmd == "status":
        sp = os.path.join(state_dir(mode), "state.json")
        print(json.dumps({"execution_mode": mode, "state": json.load(open(sp)) if os.path.exists(sp) else None}, indent=1, default=str)); return
    if a.cmd == "rebase":
        if not a.confirm: raise SystemExit("rebase reinicia pico/dia/SUSPEND/teto: usa --confirm depois de confirmares o motivo (ex. levantamento)")
        now = store.now_ms(); before, reset = (paper_rebase(rules, mode, now) if mode == "paper_autonomous" else (None, HL.reset_balance(rules)))
        ex = Executor(rules, mode, broker=None, now=now)
        ex.st.update(peak=None, day=None, suspended=False, target_latched=None, since_ts=now); ex.save()
        print(json.dumps({"rebase": "ok", "mode": mode, "paper_cash_before": before, "reset_balance": reset,
                          "note": "paper: saldo simulado reposto" if mode == "paper_autonomous" else
                          "live: o bot NÃO levanta nada; pico/dia/teto reiniciados — o saldo real (após o teu levantamento na app) é a nova base"})); return
    if a.cmd == "unkill":
        if not a.confirm: raise SystemExit("unkill limpa o KILL automático (critério de morte): usa --confirm só depois de rever o motivo")
        ex = Executor(rules, mode, broker=None); was = ex.st.get("kill_latched"); ex.st["kill_latched"] = None; ex.save()
        print(json.dumps({"unkill": "ok", "was": was}, ensure_ascii=False)); return
    if mode == "off": print("execution_mode=off — nada a fazer"); return
    while True:
        now = store.now_ms()
        try:
            ex = Executor(rules, mode, make_broker(mode, rules, now=now), now=now); res = ex.run_once()
        except (SystemExit, PermissionError): raise
        except Exception as e:
            res = on_run_failure(rules, mode, now, f"{type(e).__name__}: {str(e)[:200]}")
        print(json.dumps(res, default=str, ensure_ascii=False)[:2000])
        if a.cmd == "run-once": return
        time.sleep(a.interval); rules = load_rules(); mode = str(P(rules, "execution_mode", "off"))
        if mode == "off": print("execution_mode=off — parei"); return


if __name__ == "__main__":
    main()
