"""Runner FORWARD dos livros EMS (PAPER ONLY) → desk/state/ems_paper/forward/.
Corre dentro do ciclo de ~60 s de tools/scalp_up.sh (hook em desk/scalp/run.loop, isolado por try/except: uma falha aqui
nunca pára os 6 livros scalp). Sem broker, sem live/, sem chaves, não lê nem muda execution_mode, não escreve journal/
positions do desk, não emite alertas no outbox (o boletim lê `python -m desk.ems status`).
Depois de uma pausa do box: recupera as velas em falta (marcadas catchup) — sinais só com velas fechadas, enchimentos só
em velas seguintes, macro ponto-no-tempo, e o livro OBI não entra em velas de catchup (sem L2 histórico) ⇒ sem look-ahead.
"""
from __future__ import annotations
import csv, json, math, os, time
from datetime import datetime, timezone
from decimal import Decimal

from desk import store
from desk.scalp import feed
from . import spec as SP
from .engine import Engine, Ctx, new_state, new_book, to_json, from_json, BOOKS, SYMS, M1, DAY, BK, TRAINING, HALTED, CEILING, START, CEIL, DD_KILL
from .spec import SPEC

GRACE = SPEC["data"]["close_grace_s"] * 1000
CATCHUP_AGE = SPEC["data"]["catchup_age_s"] * 1000
WAIT_MISSING = 5 * M1
MIN_DAYS_RATIO = 7                 # Sharpe/Sortino diários só com ≥7 retornos diários (antes disso é ruído)
TRADE_COLS = ["book", "symbol", "setup", "entry_kind", "signal_ts", "fill_ts", "exit_ts", "entry", "stop", "tp", "stop_pct", "qty",
              "notional", "exit", "reason", "fee", "slip_cost", "pnl", "r_unit", "r", "catchup"]
STR_COLS = {"book", "symbol", "setup", "entry_kind", "reason"}


def base_dir():
    d = os.environ.get("EMS_STATE_DIR") or os.path.join(store.STATE, "ems_paper"); os.makedirs(d, exist_ok=True); return d


def fdir():
    d = os.path.join(base_dir(), "forward"); os.makedirs(d, exist_ok=True); return d


def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ms else None


def _atomic_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, default=str)
    os.replace(tmp, p)


def _load(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError):
        return d


def append_csv(p, cols, rows):
    if not rows: return
    new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new: w.writeheader()
        for r in rows: w.writerow({k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()})


def read_trades(d=None):
    p = os.path.join(d or fdir(), "trades.csv")
    if not os.path.exists(p): return []
    out = []
    for r in csv.DictReader(open(p)):
        for k in TRADE_COLS:
            if k in STR_COLS: continue
            if k == "catchup": r[k] = r[k] == "True"; continue
            r[k] = float(r[k]) if r.get(k) not in ("", None) else None
        out.append(r)
    return out


def read_equity(d=None):
    p = os.path.join(d or fdir(), "equity.csv")
    if not os.path.exists(p): return []
    return [{k: (int(v) if k == "ts" else float(v)) for k, v in r.items() if v not in ("", None)} for r in csv.DictReader(open(p))]


# ---------------- book L2 ----------------
def parse_book(j, now_ms):
    d = (j or {}).get("data", j) or {}
    try:
        bids = [(float(x["price"]), float(x.get("quantity", x.get("size")))) for x in d["bids"]]
        asks = [(float(x["price"]), float(x.get("quantity", x.get("size")))) for x in d["asks"]]
    except (KeyError, TypeError, ValueError):
        return None
    bids.sort(key=lambda x: -x[0]); asks.sort(key=lambda x: x[0])
    if not bids or not asks or not (0 < bids[0][0] < asks[0][0]): return None
    n = SPEC["indicators"]["obi_depth"]
    bv, av = sum(q for _, q in bids[:n]), sum(q for _, q in asks[:n])
    mid = (bids[0][0] + asks[0][0]) / 2
    return {"ts": now_ms, "bid": bids[0][0], "ask": asks[0][0], "half_spread": (asks[0][0] - bids[0][0]) / 2 / mid,
            "spread_bps": (asks[0][0] - bids[0][0]) / mid * 1e4, "obi": (bv - av) / (bv + av) if bv + av > 0 else None}


# ---------------- macro ponto-no-tempo ----------------
class Macro:
    def __init__(self):
        self.cache, self.ctx, self.rules = {}, None, None
        try:
            from desk import macro as M, rules as R
            self.M = M; self.ctx = M.load()
            try: self.rules = R.load_rules()
            except Exception: self.rules = None
        except Exception:
            self.M = None

    def __call__(self, close_ts):
        if self.M is None: return None
        h = close_ts // 3_600_000                       # séries diárias: avaliar 1×/hora chega e é ponto-no-tempo
        if h not in self.cache:
            try: self.cache[h] = self.M.evaluate(self.ctx, h * 3_600_000, self.rules)["status"]
            except Exception: self.cache[h] = None
        return self.cache[h]


# ---------------- FORWARD ----------------
class Forward:
    def __init__(self, get=feed.http_get, clock=lambda: int(time.time() * 1000), log=print, macro=None):
        self.get, self.clock, self.log = get, clock, log
        self.d = fdir(); self.p = os.path.join(self.d, "state.json"); self.meta_p = os.path.join(self.d, "meta.json")
        self.macro = macro
        self.meta = _load(self.meta_p, None) or {"books_l2": {}, "health": {"ok_runs": 0, "fail_runs": 0, "consec_fail": 0,
                                                                            "last_ok_ts": None, "first_ts": None, "last_error": None},
                                                 "events": [], "n_events_total": 0, "rebases": []}

    def _hs(self, sym, ts):
        b = self.meta["books_l2"].get(sym)
        if b and abs(ts + M1 - b["ts"]) <= 120_000 + M1: return Decimal(str(round(b["half_spread"], 8)))
        return Decimal(SPEC["execution"]["fallback_half_spread"][sym])

    def _book(self, sym, close_ts):
        return self.meta["books_l2"].get(sym)

    def init_state(self, now):
        start = (now // M1) * M1
        st = new_state(trade_from=start)
        st["forward_start"] = start; st["prereg_sha256"] = SP.check(); st["code_sha256"] = SP.code_hash()
        warm = {}
        for s in SYMS:
            rows, ok = feed.candles_1m(s, start - 999 * M1, start - M1, self.get)
            if not ok or not rows: raise RuntimeError(f"aquecimento falhou para {s}")
            warm[s] = rows
        t0 = max(r[0]["ts"] for r in warm.values()); t1 = start - M1
        st = from_json(to_json(st)); eng = Engine(st)
        grids = {s: feed.grid([r for r in warm[s] if r["ts"] >= t0], t0, t1, None)[0] for s in SYMS}
        n = min(len(g) for g in grids.values())
        for i in range(n): eng.step(grids[SYMS[0]][i]["ts"], {s: grids[s][i] for s in SYMS}, Ctx(hs=self._hs))
        eng.dump(); st["warm_bars"] = n
        return st

    def run_once(self):
        now = self.clock(); h = self.meta["health"]; h["first_ts"] = h["first_ts"] or now
        try:
            SP.check()
            raw = _load(self.p)
            st = from_json(raw) if raw else self.init_state(now)
            if not raw: _atomic_json(self.p, to_json(st))
            for s in SYMS:
                b = parse_book(self.get(f"{feed.RX2}/public/order-book/{s}", {"limit": 10}), self.clock())
                if b: self.meta["books_l2"][s] = b
            target = (now - M1 - GRACE) // M1 * M1
            frm = st["last_ts"] + M1
            if target >= frm:
                lim, new = target, {}
                for s in SYMS:
                    rows, ok = feed.candles_1m(s, frm, target, self.get)
                    if not ok: raise RuntimeError("velas 1m indisponíveis")
                    new[s] = rows
                    last_seen = rows[-1]["ts"] if rows else frm - M1
                    lim = min(lim, max(last_seen, (now - WAIT_MISSING) // M1 * M1))
                trades, events = [], []
                eng = Engine(st, on_trade=trades.append, on_event=events.append)
                macro = self.macro or Macro()
                if lim >= frm:
                    gr = {s: feed.grid([r for r in new[s] if r["ts"] <= lim], frm, lim, float(st["last_close"][s]) if s in st["last_close"] else None)[0]
                          for s in SYMS}
                    n = min(len(g) for g in gr.values())
                    for i in range(n):
                        ts = gr[SYMS[0]][i]["ts"]
                        ctx = Ctx(hs=self._hs, macro=macro, book=self._book, catchup=(now - ts) > CATCHUP_AGE + M1 + GRACE)
                        eng.step(ts, {s: gr[s][i] for s in SYMS}, ctx)
                        if ts % (5 * M1) == 0:
                            append_csv(os.path.join(self.d, "equity.csv"), ["ts"] + BOOKS,
                                       [{"ts": ts, **{b: round(float(st["books"][b]["equity"]), 4) for b in BOOKS}}])
                eng.dump()
                append_csv(os.path.join(self.d, "trades.csv"), TRADE_COLS, trades)
                self.meta["events"] = (self.meta["events"] + events)[-200:]
                self.meta["n_events_total"] = self.meta.get("n_events_total", 0) + len(events)
                for e in events: self.log(f"EMS evento: {json.dumps(e)}")
                _atomic_json(self.p, to_json(st))
            h.update(ok_runs=h["ok_runs"] + 1, consec_fail=0, last_ok_ts=now, last_error=None)
            res = {"ok": True, "last_bar": iso(st["last_ts"]), "lag_s": (now - st["last_ts"] - M1) / 1000 if st["last_ts"] else None}
        except Exception as e:
            h.update(fail_runs=h["fail_runs"] + 1, consec_fail=h["consec_fail"] + 1, last_error=f"{type(e).__name__}: {e}"[:200])
            res = {"ok": False, "error": h["last_error"]}
        self.meta["last_run"] = now
        _atomic_json(self.meta_p, self.meta)
        return res


_HOOK = {"fwd": None}


def loop_hook(log=print):
    """Chamado pelo ciclo scalp a cada ~60 s. Nunca lança excepção (isolamento dos 6 livros scalp)."""
    try:
        if _HOOK["fwd"] is None: _HOOK["fwd"] = Forward(log=log)
        r = _HOOK["fwd"].run_once()
        log(json.dumps({"ems": r}))
        return r
    except Exception as e:
        log(f"ems hook: {type(e).__name__}: {e}"); return {"ok": False, "error": type(e).__name__}


# ---------------- rebase manual (só por ordem do utilizador) ----------------
def rebase(book, confirm=False, now=None):
    if book not in BOOKS: raise SystemExit(f"livro desconhecido: {book} (válidos: {', '.join(BOOKS)})")
    if not confirm: raise SystemExit("rebase é decisão MANUAL do utilizador: repete com --confirm")
    d = fdir(); p = os.path.join(d, "state.json"); raw = _load(p)
    if not raw: raise SystemExit("sem estado forward")
    st = from_json(raw); b = st["books"][book]
    if b["pos"] or b["pend"]: raise SystemExit("livro tem posições/pendentes; só faço rebase com o livro parado e vazio")
    if b["state"] == TRAINING: raise SystemExit("livro está em PAPER_TRAINING; rebase só depois de HALTED_MAX_DRAWDOWN ou CEILING_PAUSED")
    nb = new_book(); nb["cycles"] = b.get("cycles", 0) + 1; nb["state_since"] = now or int(time.time() * 1000)
    st["books"][book] = nb; _atomic_json(p, to_json(st))
    mp = os.path.join(d, "meta.json"); meta = _load(mp, {}) or {}
    meta.setdefault("rebases", []).append({"book": book, "ts": nb["state_since"], "from_state": b["state"], "from_equity": str(b["equity"])})
    _atomic_json(mp, meta)
    return nb


# ---------------- métricas / status ----------------
def _daily(eq_rows, book):
    last = {}
    for r in eq_rows:
        if book in r: last[r["ts"] // DAY] = r[book]
    e = [last[k] for k in sorted(last)]
    return [e[i] / e[i - 1] - 1 for i in range(1, len(e)) if e[i - 1] > 0]


def metrics(trades, bs, eq_rows):
    A = SPEC["auditor"]; n = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]; losses = [-t["pnl"] for t in trades if t["pnl"] <= 0]
    rs = [t["r"] for t in trades]
    exp = sum(rs) / n if n else None; wr = len(wins) / n if n else None
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (None if not wins else math.inf)
    dd = float((bs or {}).get("max_dd", 0.0))
    dr = _daily(eq_rows, (bs or {}).get("_name"))
    mu = sum(dr) / len(dr) if dr else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in dr) / (len(dr) - 1)) if len(dr) > 1 else 0.0
    dsd = math.sqrt(sum(min(x, 0) ** 2 for x in dr) / len(dr)) if dr else 0.0
    if n < A["min_trades"]:
        verdict = "NO-GO (DD>20% já com poucos trades)" if dd > A["max_dd"] else "dados insuficientes"
    elif wr >= A["win_rate"] and exp >= A["expectancy_r"] and dd <= A["max_dd"]:
        verdict = "possível GO (só paper)"
    else:
        verdict = "NO-GO"
    return {"trades": n, "win_rate": wr, "expectancy_r": exp, "profit_factor": pf, "max_dd": dd,
            "sharpe_daily": (mu / sd * math.sqrt(365)) if sd > 0 and len(dr) >= MIN_DAYS_RATIO else None,
            "sortino_daily": (mu / dsd * math.sqrt(365)) if dsd > 0 and len(dr) >= MIN_DAYS_RATIO else None,
            "days_with_marks": len(dr) + (1 if dr else 0),
            "fees": sum(t["fee"] for t in trades), "slippage_spread": sum(t["slip_cost"] for t in trades),
            "pnl": sum(t["pnl"] for t in trades), "maker_entries": sum(1 for t in trades if t["entry_kind"] == "maker"),
            "catchup_trades": sum(1 for t in trades if t.get("catchup")), "verdict": verdict}


def report(st=None, d=None):
    d = d or fdir()
    st = st if st is not None else (_load(os.path.join(d, "state.json"), {}) or {})
    T = read_trades(d); E = read_equity(d); out = {}
    for b in BOOKS:
        bs = dict((st.get("books") or {}).get(b, {})); bs["_name"] = b
        tb = [t for t in T if t["book"] == b]
        m = metrics(tb, bs, E)
        eq = float(bs["equity"]) if bs.get("equity") is not None else None
        peak = float(bs["peak"]) if bs.get("peak") is not None else None
        m.update(name=BK[b]["name"], state=bs.get("state", TRAINING), equity=eq, peak=peak, cycles=bs.get("cycles", 0),
                 drawdown_now=(1 - eq / peak) if eq and peak else 0.0,
                 open=len(bs.get("pos") or {}), pending=len(bs.get("pend") or {}), counts=bs.get("n"),
                 ceiling_progress=(eq / float(CEIL)) if eq else 0.0)
        m["dd_room"] = float(DD_KILL) - m["drawdown_now"]
        out[b] = m
    return out


def _pidalive():
    pidf = os.path.join(feed.ROOT, "logs", "run", "scalp.pid")
    pid = open(pidf).read().strip() if os.path.exists(pidf) else None
    if not pid: return False, None
    try: os.kill(int(pid), 0); return True, pid
    except (OSError, ValueError): return False, None


def status():
    out = {"spec_id": SPEC["id"], "paper_only": True, "live_path": False}
    try: out["prereg_sha256"] = SP.check()
    except Exception as e: out["prereg_error"] = str(e)
    alive, pid = _pidalive()
    d = fdir(); st = _load(os.path.join(d, "state.json"), {}) or {}; meta = _load(os.path.join(d, "meta.json"), {}) or {}
    now = int(time.time() * 1000)
    out["forward"] = {"loop_running": alive, "pid": pid if alive else None, "started": iso(st.get("forward_start")),
                      "last_bar": iso(st.get("last_ts")), "lag_s": (now - st["last_ts"] - M1) / 1000 if st.get("last_ts") else None,
                      "last_run": iso(meta.get("last_run")), "health": meta.get("health"),
                      "l2": {s: {"spread_bps": round(v["spread_bps"], 2), "obi": round(v["obi"], 3) if v.get("obi") is not None else None,
                                 "at": iso(v["ts"])} for s, v in (meta.get("books_l2") or {}).items()},
                      "events": (meta.get("events") or [])[-10:], "n_events_total": meta.get("n_events_total", 0),
                      "books": report(st, d) if st else {}}
    return out


def _usd(x): return f"${x:,.2f}" if x is not None else "—"


def fmt_status(s):
    f = s["forward"]
    L = [f"EMS books · {s['spec_id']} · PAPER ONLY · prereg {str(s.get('prereg_sha256', s.get('prereg_error')))[:12]}",
         f"FORWARD: loop {'A CORRER pid ' + str(f['pid']) if f['loop_running'] else 'PARADO'} · início {f['started']} · "
         f"última vela {f['last_bar']} (atraso {f['lag_s']} s) · falhas seguidas {(f.get('health') or {}).get('consec_fail')}"]
    for b, m in (f["books"] or {}).items():
        wr = f"{100 * m['win_rate']:.0f}%" if m["win_rate"] is not None else "—"
        ex = f"{m['expectancy_r']:+.2f}R" if m["expectancy_r"] is not None else "—"
        pf = f"{m['profit_factor']:.2f}" if isinstance(m["profit_factor"], float) and math.isfinite(m["profit_factor"]) else str(m["profit_factor"])
        sh = f"{m['sharpe_daily']:.2f}" if m["sharpe_daily"] is not None else "—"
        L.append(f"  {b:<15} n={m['trades']:<3}/40 WR {wr:<4} {ex:<7} PF {pf:<5} Sharpe {sh:<5} DD {100 * m['max_dd']:.1f}% "
                 f"(agora {100 * m['drawdown_now']:.1f}%) eq {_usd(m['equity'])} abertas {m['open']} pend {m['pending']} "
                 f"{m['state']} → {m['verdict']}" + (f" · catchup {m['catchup_trades']}/{m['trades']}" if m.get("catchup_trades") else ""))
    for e in f.get("events") or []:
        L.append(f"  ⚠ {e.get('book')}: {e.get('type')} em {iso(e.get('ts'))} (equity {e.get('equity')})")
    return "\n".join(L)


# ---------------- dados para o painel (só leitura, sem segredos) ----------------
def dashboard_data(max_bars=180, max_trades=40):
    d = fdir(); st = _load(os.path.join(d, "state.json"), {}) or {}; meta = _load(os.path.join(d, "meta.json"), {}) or {}
    if not st: return {"available": False, "why": "forward ainda não arrancou"}
    rep = report(st, d); T = read_trades(d)
    cards = []
    for b, m in rep.items():
        bs = st["books"][b]
        cards.append({"id": b, "name": m["name"], "state": m["state"], "equity": m["equity"], "start": float(START),
                      "ceiling": float(CEIL), "ceiling_progress": m["ceiling_progress"], "drawdown_now": m["drawdown_now"],
                      "dd_limit": float(DD_KILL), "dd_room": m["dd_room"], "max_dd": m["max_dd"], "trades": m["trades"],
                      "need_trades": SPEC["auditor"]["min_trades"], "win_rate": m["win_rate"], "expectancy_r": m["expectancy_r"],
                      "profit_factor": m["profit_factor"] if m["profit_factor"] is None or math.isfinite(m["profit_factor"]) else None,
                      "sharpe": m["sharpe_daily"], "sortino": m["sortino_daily"], "pnl": m["pnl"], "fees": m["fees"],
                      "verdict": m["verdict"], "cycles": m["cycles"], "counts": m["counts"],
                      "positions": [{"coin": s, "entry": float(p["entry"]), "stop": float(p["stop"]), "tp": float(p["tp"]),
                                     "qty": float(p["qty"]), "since": p["fill_ts"], "kind": p["kind"], "setup": p["setup"]}
                                    for s, p in (bs.get("pos") or {}).items()],
                      "orders": [{"coin": s, "kind": q["kind"], "limit": float(q["limit"]) if q.get("limit") else None,
                                  "stop": float(q["stop"]), "tp": float(q["tp"]), "placed": q["signal_ts"], "expires": q["expiry"]}
                                 for s, q in (bs.get("pend") or {}).items()]})
    candles = {s: [[r[0], round(r[1], 8), round(r[2], 8), round(r[3], 8), round(r[4], 8)] for r in (st.get("recent") or {}).get(s, [])[-max_bars:]]
               for s in SYMS}
    marks = [{"book": t["book"], "coin": t["symbol"], "fill": int(t["fill_ts"]), "exit": int(t["exit_ts"]), "entry": t["entry"],
              "exit_px": t["exit"], "stop": t["stop"], "tp": t["tp"], "r": t["r"], "pnl": t["pnl"], "reason": t["reason"],
              "kind": t["entry_kind"], "catchup": t["catchup"]} for t in T[-max_trades:]]
    E = read_equity(d)[-288:]
    return {"available": True, "spec_id": SPEC["id"], "started": st.get("forward_start"), "last_bar": st.get("last_ts"),
            "symbols": SYMS, "cards": cards, "candles": candles, "trades": marks,
            "curve": {b: [[r["ts"], r.get(b)] for r in E] for b in BOOKS},
            "l2": {s: {"spread_bps": round(v["spread_bps"], 2), "obi": round(v["obi"], 3) if v.get("obi") is not None else None, "at": v["ts"]}
                   for s, v in (meta.get("books_l2") or {}).items()},
            "events": (meta.get("events") or [])[-10:],
            "rules": {"start": float(START), "ceiling": float(CEIL), "dd_kill": float(DD_KILL), "maker_fee": 0.0, "taker_fee": 0.0009,
                      "slippage": 0.001, "taker_min_edge": 0.0035, "risk_pct": 0.01, "min_trades": 40}}
