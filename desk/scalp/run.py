"""Runner dos bots Scalp (PAPER ONLY). Dois fluxos SEPARADOS, nunca misturados:
  REPLAY  → desk/state/scalp_paper/replay/   (histórico 1m recente da Revolut X, rótulo REPLAY)
  FORWARD → desk/state/scalp_paper/forward/  (velas fechadas depois do arranque; ciclo ~60 s)
Isolamento: sem broker, sem live/, sem chaves (env REVX_* ignorado/removido), não lê nem muda execution_mode, não escreve
journal/positions do desk (não conta para o GO do auditor). Único contacto com o desk: no máximo 1 SCALP_SUMMARY/hora no outbox.
"""
from __future__ import annotations
import csv, json, os, sys, time
from datetime import datetime, timezone

from desk import store
from . import feed, spec as SP
from .engine import Engine, new_state, BOOKS, SYMS, M1, D, metrics, BOTS, bot_of
from .spec import SPEC

TYPE = "SCALP_SUMMARY"
GRACE = SPEC["data"]["close_grace_s"] * 1000
WAIT_MISSING = 5 * M1          # minuto sem vela: espera até 5 min antes de o tratar como "sem negócios" (sintético)
CATCHUP_AGE = 3 * M1
TRADE_COLS = ["book", "symbol", "signal_ts", "fill_ts", "exit_ts", "entry", "stop", "tp", "stop_pct", "qty", "notional", "exit",
              "reason", "fee", "slip_cost", "pnl", "r_unit", "r", "catchup"]


def base_dir():
    d = os.environ.get("SCALP_STATE_DIR") or os.path.join(store.STATE, "scalp_paper"); os.makedirs(d, exist_ok=True); return d


def sdir(stream):
    d = os.path.join(base_dir(), stream); os.makedirs(d, exist_ok=True); return d


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
        for r in rows: w.writerow(r)


def read_trades(stream):
    p = os.path.join(sdir(stream), "trades.csv")
    if not os.path.exists(p): return []
    out = []
    for r in csv.DictReader(open(p)):
        for k in TRADE_COLS:
            if k in ("book", "symbol", "reason"): continue
            if k == "catchup": r[k] = r[k] == "True"; continue
            r[k] = float(r[k]) if r[k] not in ("", None) else None
        out.append(r)
    return out


def report(stream, st=None):
    st = st or _load(os.path.join(sdir(stream), "state.json"), {}) or {}
    T = read_trades(stream); out = {}
    for b in BOOKS:
        bs = (st.get("books") or {}).get(b, {})
        tb = [t for t in T if t["book"] == b]
        m = metrics(tb, bs)
        m["catchup_trades"] = sum(1 for t in tb if t.get("catchup"))   # trades recuperados após pausa do box/reinício
        m.update(name=BOTS[bot_of(b)]["name"] + (" + filtro ADX" if b.endswith("_adx") else " (sem filtro)"),
                 equity=bs.get("equity"), counts=bs.get("n"), open=len(bs.get("pos") or {}), pending=len(bs.get("pend") or {}),
                 state=("KILL (DD>20%)" if bs.get("killed") else "TETO" if bs.get("ceiling") else
                        "PARADO HOJE (−2%)" if bs.get("halted_until") is not None else "RUNNING"))
        out[b] = m
    return out


# ---------------- REPLAY ----------------
def replay(max_days=40, refresh=True, log=print):
    sha = SP.check()
    cache = os.path.join(feed.ROOT, "data_ext", "revx_1m"); os.makedirs(cache, exist_ok=True)
    data = {}
    for s in SYMS:
        p = os.path.join(cache, f"{s}.json")
        if refresh or not os.path.exists(p):
            rows = feed.history(s, max_days=max_days, log=log); _atomic_json(p, rows); log(f"{s}: {len(rows)} velas 1m")
        data[s] = _load(p, [])
    now = int(time.time() * 1000)
    t0 = max(min(r["ts"] for r in data[s]) for s in SYMS)
    t1 = min(max(r["ts"] for r in data[s]) for s in SYMS)
    t1 = min(t1, (now - M1 - GRACE) // M1 * M1)
    grids, dq = {}, {}
    for s in SYMS:
        first_c = next(r["c"] for r in data[s] if r["ts"] >= t0)
        g, syn = feed.grid([r for r in data[s] if t0 <= r["ts"] <= t1], t0, t1, first_c)
        grids[s] = g
        dq[s] = {"minutes": len(g), "missing_filled": syn, "zero_volume": sum(1 for r in g if r["v"] == 0),
                 "missing_pct": syn / len(g), "zero_volume_pct": sum(1 for r in g if r["v"] == 0) / len(g)}
    d = sdir("replay")
    for f in ("trades.csv", "equity.csv"):
        if os.path.exists(os.path.join(d, f)): os.remove(os.path.join(d, f))
    trade_from = -(-(t0 + D) // D) * D          # ≥24 h só a aquecer, depois começa num dia UTC inteiro
    st = new_state(trade_from); trades, eqrows, events = [], [], []
    hs_fix = SPEC["execution"]["replay_half_spread"]
    eng = Engine(st, lambda sym, ts: hs_fix[sym], on_trade=trades.append, on_event=events.append)
    n = len(grids[SYMS[0]])
    for i in range(n):
        ts = grids[SYMS[0]][i]["ts"]
        eng.step(ts, {s: grids[s][i] for s in SYMS})
        if ts % (15 * M1) == 0: eqrows.append({"ts": ts, **{b: round(st["books"][b]["equity"], 4) for b in BOOKS}})
    eng.dump()
    for t in trades: t["stream"] = "REPLAY"
    append_csv(os.path.join(d, "trades.csv"), TRADE_COLS, trades)
    append_csv(os.path.join(d, "equity.csv"), ["ts"] + BOOKS, eqrows)
    _atomic_json(os.path.join(d, "state.json"), st)
    rep = {"stream": "REPLAY", "label": "REPLAY — histórico recente Revolut X, NÃO é forward, nunca somado ao forward",
           "spec_id": SPEC["id"], "prereg_sha256": sha, "code_sha256": SP.code_hash(), "generated_at": iso(now),
           "data_from": iso(t0), "trade_from": iso(trade_from), "data_to": iso(t1), "days_traded": (t1 - trade_from) / D,
           "data_quality": dq, "events": events[-50:], "n_events": len(events), "books": report("replay", st)}
    _atomic_json(os.path.join(d, "report.json"), rep)
    return rep


# ---------------- FORWARD ----------------
class Forward:
    def __init__(self, get=feed.http_get, clock=lambda: int(time.time() * 1000), log=print):
        self.get, self.clock, self.log = get, clock, log
        self.d = sdir("forward"); self.p = os.path.join(self.d, "state.json")
        self.meta_p = os.path.join(self.d, "meta.json")
        self.meta = _load(self.meta_p, None) or {"spreads": {}, "health": {"ok_runs": 0, "fail_runs": 0, "consec_fail": 0,
                                                                          "last_ok_ts": None, "first_ts": None, "last_error": None},
                                                 "last_summary_hour": None, "summary_trades_seen": 0, "summary_events_seen": 0,
                                                 "events": []}

    def _hs(self, sym, ts):
        b = self.meta["spreads"].get(sym)
        if b and abs(ts + M1 - b["ts"]) <= SPEC["execution"]["book_max_age_s"] * 1000 + M1: return b["half_spread"]
        return SPEC["execution"]["replay_half_spread"][sym]

    def init_state(self, now):
        start = (now // M1) * M1
        st = new_state(trade_from=start)
        st["forward_start"] = start; st["prereg_sha256"] = SP.check(); st["code_sha256"] = SP.code_hash()
        # aquecimento: ≤1000 velas 1m anteriores, só indicadores (ts < trade_from ⇒ sem sinais)
        warm = {}
        for s in SYMS:
            rows, ok = feed.candles_1m(s, start - 999 * M1, start - M1, self.get)
            if not ok or not rows: raise RuntimeError(f"aquecimento falhou para {s}")
            warm[s] = rows
        t0 = max(r[0]["ts"] for r in warm.values()); t1 = start - M1
        eng = Engine(st, self._hs)
        grids = {s: feed.grid([r for r in warm[s] if r["ts"] >= t0], t0, t1, None)[0] for s in SYMS}
        n = min(len(g) for g in grids.values())
        for i in range(n): eng.step(grids[SYMS[0]][i]["ts"], {s: grids[s][i] for s in SYMS})
        eng.dump(); st["warm_bars"] = n
        return st

    def run_once(self):
        now = self.clock(); h = self.meta["health"]; h["first_ts"] = h["first_ts"] or now
        try:
            SP.check()
            st = _load(self.p)
            if not st: st = self.init_state(now); _atomic_json(self.p, st)
            for s in SYMS:
                b = feed.book(s, self.get)
                if b: self.meta["spreads"][s] = b
            target = (now - M1 - GRACE) // M1 * M1
            frm = st["last_ts"] + M1
            new, ok_all = {}, True
            if target >= frm:
                lim = target
                for s in SYMS:
                    rows, ok = feed.candles_1m(s, frm, target, self.get)
                    if not ok: ok_all = False; break
                    new[s] = rows
                    last_seen = rows[-1]["ts"] if rows else frm - M1
                    lim = min(lim, max(last_seen, (now - WAIT_MISSING) // M1 * M1))
                if not ok_all: raise RuntimeError("velas 1m indisponíveis")
                trades, events = [], []
                eng = Engine(st, self._hs, on_trade=trades.append, on_event=events.append)
                if lim >= frm:
                    gr = {s: feed.grid([r for r in new[s] if r["ts"] <= lim], frm, lim, st["last_close"].get(s))[0] for s in SYMS}
                    n = min(len(g) for g in gr.values())
                    for i in range(n):
                        ts = gr[SYMS[0]][i]["ts"]; eng.catchup = (now - ts) > CATCHUP_AGE + M1 + GRACE
                        eng.step(ts, {s: gr[s][i] for s in SYMS})
                        if ts % (5 * M1) == 0:
                            append_csv(os.path.join(self.d, "equity.csv"), ["ts"] + BOOKS,
                                       [{"ts": ts, **{b: round(st["books"][b]["equity"], 4) for b in BOOKS}}])
                eng.dump()
                for t in trades: t["stream"] = "FORWARD"
                append_csv(os.path.join(self.d, "trades.csv"), TRADE_COLS, trades)
                for e in events: e["stream"] = "FORWARD"
                self.meta["events"] = (self.meta["events"] + events)[-200:]
                self.meta["n_events_total"] = self.meta.get("n_events_total", 0) + len(events)
                _atomic_json(self.p, st)
            h.update(ok_runs=h["ok_runs"] + 1, consec_fail=0, last_ok_ts=now, last_error=None)
            res = {"ok": True, "last_bar": iso(st["last_ts"]), "lag_s": (now - st["last_ts"] - M1) / 1000 if st["last_ts"] else None}
        except Exception as e:
            h.update(fail_runs=h["fail_runs"] + 1, consec_fail=h["consec_fail"] + 1, last_error=f"{type(e).__name__}: {e}"[:200])
            res = {"ok": False, "error": h["last_error"]}
        self.meta["last_run"] = now; self.meta["api"] = dict(feed.STATS)
        try: self.maybe_summary(now)
        except Exception as e: self.log(f"summary: {type(e).__name__}: {e}")
        _atomic_json(self.meta_p, self.meta)
        return res

    def maybe_summary(self, now, emit=store.emit):
        hour = now // 3_600_000
        if self.meta.get("last_summary_hour") == hour: return None
        T = read_trades("forward"); ne = self.meta.get("n_events_total", 0)
        new_t = T[self.meta.get("summary_trades_seen", 0):]; new_e = ne - self.meta.get("summary_events_seen", 0)
        if not new_t and not new_e: return None
        alert = summary_alert(hour, new_t, self.meta["events"][-new_e:] if new_e else [], report("forward"))
        emit(alert)
        self.meta.update(last_summary_hour=hour, summary_trades_seen=len(T), summary_events_seen=ne)
        return alert


def _usd(x): return f"${x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if x is not None else "—"


def summary_alert(hour, new_trades, new_events, rep):
    hhmm = datetime.fromtimestamp(hour * 3600, timezone.utc).strftime("%Y-%m-%dT%H")
    L = ["🧪 SIMULADO · Bots Scalp (paper, preços reais Revolut X, nenhuma ordem real) — resumo da última hora",
         f"Novas operações fechadas: {len(new_trades)}" + (f" · resultado {_usd(sum(t['pnl'] for t in new_trades))}" if new_trades else "")]
    for e in new_events:
        L.append(f"⏸️ {e['book']}: {e['type']} (equity {_usd(e.get('equity'))})")
    for b, m in rep.items():
        if not m["trades"] and not m["open"]: continue
        L.append(f"• {m['name']}: {m['trades']} trades, acerto {('%.0f%%' % (100 * m['win_rate'])) if m['win_rate'] is not None else '—'}, "
                 f"{('%+.2fR' % m['expectancy_r']) if m['expectancy_r'] is not None else '—'}, equity {_usd(m['equity'])} → {m['verdict']}")
    L.append("Lembrete: o teste histórico (proxy Binance) já deu NÃO VALIDADA a estas 3 famílias; isto é só verificação forward.")
    return {"id": f"SCALP_SUMMARY:{hhmm}", "type": TYPE, "mode": "scalp_paper", "tag": SPEC["id"], "autonomous": True,
            "reply_options": [], "coin": None, "text": "\n".join(L),
            "data": {"new_trades": len(new_trades), "new_events": len(new_events),
                     "books": {b: {k: m[k] for k in ("trades", "win_rate", "expectancy_r", "equity", "verdict")} for b, m in rep.items()}}}


def loop(every=60, log=print):
    f = Forward(log=log)
    while True:
        t = time.time(); r = f.run_once(); log(json.dumps({"t": iso(int(t * 1000)), **r}))
        try:                                   # livros EMS (paper, desk/ems) no mesmo ciclo; isolados: nunca partem o scalp
            from desk.ems.run import loop_hook
            loop_hook(log)
        except Exception as e:
            log(f"ems: {type(e).__name__}")
        time.sleep(max(5.0, every - (time.time() - t)))


# ---------------- status ----------------
def status():
    out = {"spec_id": SPEC["id"], "paper_only": True}
    try: out["prereg_sha256"] = SP.check()
    except Exception as e: out["prereg_error"] = str(e)
    pidf = os.path.join(feed.ROOT, "logs", "run", "scalp.pid")
    pid = open(pidf).read().strip() if os.path.exists(pidf) else None
    alive = False
    if pid:
        try: os.kill(int(pid), 0); alive = True
        except (OSError, ValueError): pass
    fd = sdir("forward"); st = _load(os.path.join(fd, "state.json"), {}) or {}; meta = _load(os.path.join(fd, "meta.json"), {}) or {}
    now = int(time.time() * 1000)
    out["forward"] = {"loop_running": alive, "pid": pid if alive else None, "started": iso(st.get("forward_start")),
                      "last_bar": iso(st.get("last_ts")), "lag_s": (now - st["last_ts"] - M1) / 1000 if st.get("last_ts") else None,
                      "last_run": iso(meta.get("last_run")), "health": meta.get("health"),
                      "spreads_bps": {s: round(2e4 * v["half_spread"], 2) for s, v in (meta.get("spreads") or {}).items()},
                      "books": report("forward", st) if st else {}}
    rp = _load(os.path.join(sdir("replay"), "report.json"))
    if rp: out["replay"] = {k: rp[k] for k in ("label", "data_from", "trade_from", "data_to", "days_traded", "data_quality", "books")}
    return out


def fmt_status(s):
    L = [f"Scalp bots · {s['spec_id']} · PAPER ONLY · prereg {str(s.get('prereg_sha256', s.get('prereg_error')))[:12]}"]
    f = s["forward"]
    L.append(f"FORWARD: loop {'A CORRER pid ' + str(f['pid']) if f['loop_running'] else 'PARADO'} · início {f['started']} · "
             f"última vela {f['last_bar']} (atraso {f['lag_s']} s) · spreads bps {f['spreads_bps']}")
    for stream, books in (("FORWARD", f["books"]), ("REPLAY", (s.get("replay") or {}).get("books") or {})):
        if not books: continue
        if stream == "REPLAY": L.append(f"REPLAY ({s['replay']['trade_from']} → {s['replay']['data_to']}, {s['replay']['days_traded']:.1f} d):")
        for b, m in books.items():
            wr = f"{100 * m['win_rate']:.0f}%" if m["win_rate"] is not None else "—"
            ex = f"{m['expectancy_r']:+.2f}R" if m["expectancy_r"] is not None else "—"
            pf = f"{m['profit_factor']:.2f}" if isinstance(m["profit_factor"], float) else str(m["profit_factor"])
            st_ = f"{100 * m['avg_stop_pct']:.3f}%" if m["avg_stop_pct"] is not None else "—"
            L.append(f"  [{stream}] {b:<11} n={m['trades']:<4} WR {wr:<4} {ex:<7} PF {pf:<5} DD {100 * m['max_dd']:.1f}% "
                     f"custos ${m['fees'] + m['slippage_spread']:.2f} stop méd {st_} eq ${(m['equity'] or 0):.2f} {m['state']} → {m['verdict']}"
                     + (f" · catchup {m['catchup_trades']}/{m['trades']}" if stream == "FORWARD" and m.get("catchup_trades") else ""))
    return "\n".join(L)
