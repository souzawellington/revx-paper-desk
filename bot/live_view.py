"""Vista ao vivo SOMENTE-LEITURA dos 4 bots paper (página /live, JSON /api/live).

Bots: D executor (paper_autonomous + paper_fast), A c3 (tetos 12,5%), A c3_raw, B bh_btc.
Fontes: ficheiros de estado em desk/state (só leitura) + desk.health.report() (critérios de morte) + preços públicos
Revolut X (cache, 1 req/s via RateLimiter do cliente; em 502 serve o último preço bom marcado como «stale», ou o último
preço marcado pelos bots). Este módulo NUNCA escreve estado dos bots, nunca coloca ordens e nunca lê chaves.
O único ficheiro que escreve é o seu próprio log de marcações (logs/dashboard_marks.jsonl) para a curva de equity ao vivo.
"""
from __future__ import annotations
import csv, json, os, re, threading, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
START = 65.0
BOT_META = {
    "D_executor": {"name": "Bot D · mesa original (ensaio rápido)", "short": "D"},
    "A_c3": {"name": "Bot A · C3 com teto 12,5% (não validada)", "short": "A"},
    "A_c3_raw": {"name": "Bot A · C3 sem teto (não validada)", "short": "A'"},
    "B_bh_btc": {"name": "Bot B · segurar BTC (comparação)", "short": "B"},
}
_PATH_RE = re.compile(r"(/[\w.\-~]+){2,}")


def _clean(s) -> str:
    """Remove caminhos de ficheiros de mensagens de erro (nunca expor paths)."""
    return _PATH_RE.sub("<path>", str(s))[:200]


def london(ts) -> str | None:
    """ISO 'Z' / ms / s -> 'dd/mm HH:MM (Londres)'."""
    if ts in (None, ""): return None
    try:
        if isinstance(ts, (int, float)) or str(ts).isdigit():
            v = float(ts); v = v / 1000 if v > 1e11 else v
            d = datetime.fromtimestamp(v, timezone.utc)
        else:
            d = datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return d.astimezone(LONDON).strftime("%d/%m %H:%M")
    except (ValueError, OverflowError, OSError):
        return None


def _epoch(ts) -> int | None:
    try:
        if isinstance(ts, (int, float)) or str(ts).isdigit():
            v = float(ts); return int(v / 1000 if v > 1e11 else v)
        return int(datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


def _json(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception:
        return d


def _csv(p):
    try:
        with open(p, newline="") as f: return list(csv.DictReader(f))
    except Exception:
        return []


def _f(x, d=None):
    try: return float(x)
    except (TypeError, ValueError): return d


class Prices:
    """Preços públicos Revolut X com cache (ttl) e fallback no último bom valor. pub: cliente só-leitura."""
    def __init__(self, pub, region=None, ttl=20.0, clock=time.time):
        self.pub, self.region, self.ttl, self.clock = pub, region, ttl, clock
        self.lock = threading.Lock(); self.good = {}; self.good_ts = None; self.last_try = 0.0; self.err = None; self.syms = set()

    def get(self, symbols) -> dict:
        symbols = sorted(set(symbols))
        with self.lock:
            need = set(symbols) - set(self.good)
            fresh = self.clock() - self.last_try < self.ttl and not (need - self.syms)
            if not fresh:
                self.last_try = self.clock(); self.syms |= set(symbols)
                try:
                    out = {}
                    for t in self.pub.public_tickers(sorted(self.syms), self.region):
                        k = t["symbol"].replace("/", "-")
                        if k in out: continue
                        out[k] = {x: float(t[x]) for x in ("bid", "ask", "mid", "last_price") if t.get(x) not in (None, "")}
                        if t.get("price_change_24h") not in (None, "") and t.get("last_price"):
                            lp = float(t["last_price"]); ch = float(t["price_change_24h"])
                            out[k]["chg24"] = ch / (lp - ch) if lp - ch else None
                    if out:
                        self.good.update(out); self.good_ts = self.clock(); self.err = None
                except Exception as e:
                    msg = str(e)
                    self.err = "Revolut X indisponível (502)" if "502" in msg else _clean(f"{type(e).__name__}: {msg}")
            age = (self.clock() - self.good_ts) if self.good_ts else None
            return {"px": {s: self.good[s] for s in symbols if s in self.good}, "error": self.err,
                    "age_s": round(age, 1) if age is not None else None,
                    "stale": bool(self.err) or age is None or age > 3 * self.ttl,
                    "updated": london(self.good_ts) if self.good_ts else None}


def _mid(px, sym, fallback=None):
    v = (px.get(sym) or {}).get("mid")
    return v if v else fallback


def _state_dir():
    from desk import store
    return store.STATE


def executor_view(mode, px):
    d = os.path.join(_state_dir(), f"exec_{mode}")
    st = _json(os.path.join(d, "state.json"), {}) or {}
    ex = _json(os.path.join(d, "paper_exchange.json"), {}) or {}
    bal = ex.get("bal") or {}
    pos, recent = [], []
    for p in (st.get("positions") or {}).values():
        sym = p.get("symbol")
        if p.get("status") == "OPEN":
            q = _f(p.get("qty"), 0.0); e = _f(p.get("entry")) or _f(p.get("avg_entry"))
            cur = _mid(px, sym)
            pos.append({"coin": sym, "qty": q, "entry": e, "stop": _f(p.get("stop")), "tp": _f(p.get("tp")), "price": cur,
                        "unrealized": (q * (cur - e)) if (cur and e) else None,
                        "unrealized_pct": ((cur / e) - 1) if (cur and e) else None, "opened": london(p.get("opened_ts"))})
        else:
            q = _f(p.get("qty"), _f(p.get("filled"), 0.0)) or 0.0
            e = _f(p.get("entry")) or _f(p.get("avg_entry")); x = _f(p.get("exit"))
            recent.append({"ts": london(p.get("closed_ts") or p.get("placed_ts")), "_t": p.get("closed_ts") or p.get("placed_ts") or 0,
                           "coin": sym, "side": "VENDA" if p.get("status") == "CLOSED" else "COMPRA",
                           "status": {"CLOSED": "fechada", "CANCELLED": "cancelada (sem execução)"}.get(p.get("status"), p.get("status")),
                           "price": x if x else (p.get("limit")), "entry": e,
                           "pnl": (q * (x - e)) if (x and e) else None, "reason": p.get("exit_rule") or ""})
    recent.sort(key=lambda r: r.pop("_t") or 0, reverse=True)
    eq = _f(bal.get("USD"), 0.0)
    for c, q in bal.items():
        if c == "USD": continue
        m = _mid(px, f"{c}-USD")
        if m: eq += float(q) * m
    if not bal: eq = None
    eqrows = [(int(r["ts_ms"]) // 1000, _f(r["equity"])) for r in _csv(os.path.join(d, "equity.csv")) if r.get("ts_ms")]
    if st.get("enabled_ts"): eqrows = [(int(st["enabled_ts"]) // 1000, START)] + eqrows
    return {"equity_live": eq, "peak": st.get("peak"), "positions": pos, "recent": recent[:10], "curve": eqrows}


def c3_view(book, px):
    from desk.shadow import c3 as C
    d = C.state_dir()
    st = _json(os.path.join(d, "state.json"), {}) or {}
    b = (st.get("books") or {}).get(book)
    if not b: return {"equity_live": None, "positions": [], "recent": [], "curve": []}
    lm = (st.get("last_mark") or {}).get("mid") or {}
    eq, pos = b.get("cash", 0.0), []
    for a, q in (b.get("units") or {}).items():
        if not q: continue
        cur = _mid(px, f"{a}-USD", lm.get(a)); avg = _f((b.get("avg") or {}).get(a))
        eq += q * (cur or 0)
        pos.append({"coin": f"{a}-USD", "qty": q, "entry": avg, "stop": (avg * (1 - C.STOP)) if (avg and book != "bh_btc") else None,
                    "tp": None, "price": cur, "unrealized": q * (cur - avg) if (cur and avg) else None,
                    "unrealized_pct": (cur / avg - 1) if (cur and avg) else None, "opened": (b.get("entry_day") or {}).get(a)})
    recent = []
    for t in reversed(_csv(os.path.join(d, "trades.csv"))):
        if t.get("book") != book: continue
        recent.append({"ts": london(t.get("ts")), "coin": f"{t.get('coin')}-USD", "side": "COMPRA" if t.get("side") == "BUY" else "VENDA",
                       "status": "executada (simulada)", "price": _f(t.get("price")), "entry": None, "pnl": None,
                       "reason": t.get("reason"), "notional": _f(t.get("notional_usd")), "fee": _f(t.get("fee_usd"))})
        if len(recent) >= 10: break
    t0 = _epoch(st.get("created_at"))
    curve = [(t0 - 1, START)] if t0 else []
    for r in _csv(os.path.join(d, "equity.csv")):
        t, v = _epoch(r.get("ts")), _f(r.get(book))
        if t and v is not None: curve.append((t, v))
    return {"equity_live": eq, "peak": b.get("peak"), "positions": pos, "recent": recent, "curve": curve,
            "signal": (st.get("last_signal") or {}).get(book)}


SCALP_SHORT = {"bb_rsi": "S1", "bb_rsi_adx": "S1f", "ema_pb": "S2", "ema_pb_adx": "S2f", "brk": "S3", "brk_adx": "S3f"}


def scalp_cards(now=None) -> list:
    """Cartões SÓ LEITURA dos bots Scalp (paper, forward). Lê desk/state/scalp_paper/forward; nunca escreve, nunca põe ordens."""
    try:
        from desk.scalp import run as SR, engine as SE
    except Exception:
        return []
    from desk import store
    d = os.path.join(os.environ.get("SCALP_STATE_DIR") or os.path.join(store.STATE, "scalp_paper"), "forward")
    st = _json(os.path.join(d, "state.json"), None) if os.path.isdir(d) else None
    if not st: return []
    meta = _json(os.path.join(d, "meta.json"), {}) or {}
    rep = SR.report("forward", st); T = SR.read_trades("forward")
    eqrows = _csv(os.path.join(d, "equity.csv"))[-2000:]
    lag = ((now or time.time()) * 1000 - st["last_ts"] - 60_000) / 1000 if st.get("last_ts") else None
    out = []
    for b in SE.BOOKS:
        m, bs = rep[b], st["books"][b]
        pos = [{"coin": sym, "qty": p["qty"], "entry": p["entry"], "stop": p["stop"], "tp": p["tp"],
                "price": (st.get("last_close") or {}).get(sym), "opened": london(p["fill_ts"] / 1000),
                "unrealized": p["qty"] * ((st.get("last_close") or {}).get(sym, p["entry"]) - p["entry"]),
                "unrealized_pct": ((st.get("last_close") or {}).get(sym, p["entry"]) / p["entry"] - 1)} for sym, p in bs["pos"].items()]
        recent = [{"ts": london(t["exit_ts"] / 1000), "coin": t["symbol"], "side": "VENDA", "status": "fechada (simulada)",
                   "price": t["exit"], "entry": t["entry"], "pnl": t["pnl"], "reason": f"{t['reason']} ({t['r']:+.2f}R)"}
                  for t in reversed([t for t in T if t["book"] == b][-10:])]
        crit = [{"key": "trades", "name": "Trades (auditor ≥ 40)", "value": str(m["trades"]), "limit": "≥ 40", "status": "OK" if m["trades"] >= 40 else "aguardando dados", "tripped": False, "info": True},
                {"key": "wr", "name": "Acerto (≥ 33%)", "value": f"{100 * m['win_rate']:.0f}%" if m["win_rate"] is not None else "—", "limit": "≥ 33%", "status": "OK" if (m["win_rate"] or 0) >= 0.33 else "abaixo", "tripped": False, "info": True},
                {"key": "exp", "name": "Expectativa (≥ +0,4R)", "value": f"{m['expectancy_r']:+.2f}R" if m["expectancy_r"] is not None else "—", "limit": "≥ +0,40R", "status": "OK" if (m["expectancy_r"] or -9) >= 0.4 else "abaixo", "tripped": False, "info": True},
                {"key": "verdict", "name": "Veredito", "value": m["verdict"], "limit": "40 trades · 33% · +0,4R · DD ≤ 20%", "status": m["verdict"], "tripped": False, "info": True},
                {"key": "daily", "name": "Kill diário −2%", "value": "parado hoje" if bs.get("halted_until") is not None else "ok", "limit": "−2% no dia UTC", "status": "DISPAROU" if bs.get("halted_until") is not None else "OK", "tripped": bs.get("halted_until") is not None, "info": False},
                {"key": "dd", "name": "Kill DD > 20%", "value": f"{100 * m['max_dd']:.1f}%", "limit": "> 20%", "status": "DISPAROU" if bs.get("killed") else "OK", "tripped": bool(bs.get("killed")), "info": False}]
        curve = [(int(r["ts"]) // 1000, _f(r.get(b))) for r in eqrows if r.get("ts")]
        eq = bs["equity"]
        out.append({"key": f"S_{b}", "name": f"Scalp {SCALP_SHORT[b]} · {m['name']} (SIMULADO, não validada)", "short": SCALP_SHORT[b],
                    "available": True, "paper": True, "state": m["state"], "equity": eq, "start": START,
                    "pnl": eq - START, "pnl_pct": eq / START - 1, "drawdown": (bs["peak"] - eq) / bs["peak"] if bs["peak"] else None,
                    "ceiling": 1000.0, "to_ceiling": 1000.0 - eq, "ceiling_progress": eq / 1000.0, "ceiling_latched": bool(bs.get("ceiling")),
                    "killed": bool(bs.get("killed")), "positions": pos, "recent": recent, "signal": None, "criteria": crit,
                    "any_tripped": bool(bs.get("killed") or bs.get("halted_until") is not None),
                    "last_run": london(meta.get("last_run") / 1000) if meta.get("last_run") else None,
                    "data_lag_s": lag, "curve": [[t, round(v, 4)] for t, v in curve if v is not None] + [[int(now or time.time()), round(eq, 4)]]})
    return out


def _crit_view(crit: dict) -> list:
    names = {"forward_dd": "Queda máxima (DD)", "sharpe_12m": "Sharpe 12 meses", "divergence": "Divergência vs backtest",
             "data_stale": "Dados Revolut X parados", "data_gap_revx": "Falha de velas diárias Revolut X", "api_errors": "Erros de API"}
    out = []
    for k, v in (crit or {}).items():
        if not isinstance(v, dict): continue
        meas = v.get("measurable", True)
        out.append({"key": k, "name": names.get(k, k), "value": str(v.get("value")), "limit": str(v.get("limit")),
                    "status": "DISPAROU" if v.get("tripped") else ("aguardando dados" if meas is False else "OK"),
                    "tripped": bool(v.get("tripped")), "info": bool(v.get("informational"))})
    return out


def desk_view(rules):
    from desk import store
    from desk.auditor import stats
    from desk.rules import PAPER_FAST_TAG
    s, fast = stats(rules), stats(rules, tag=PAPER_FAST_TAG)
    th = {k: rules.p.get(k) for k in ("threshold_trades", "threshold_win_rate", "threshold_expectancy_r", "threshold_max_dd")}
    open_ = [{"coin": p["coin"], "entry": _f(p["entry"]), "stop": _f(p["stop"]), "tp": _f(p.get("tp_price")),
              "opened": london(p.get("opened_ts")), "tag": p.get("tag") or ""} for p in store.read("positions.csv") if p.get("status") == "OPEN"]
    res = [r for r in store.read("journal.csv") if r.get("line") == "RESULT" and r.get("mode") == "PAPER"][-10:][::-1]
    return {"n": s["n"], "win_rate": s["win_rate"], "expectancy_r": s["expectancy_r"], "max_dd": s["max_dd"], "go": s["go"],
            "thresholds": th, "checks": {k: bool(v[1]) for k, v in s["thresholds"].items()},
            "fast": {"n": fast["n"], "win_rate": fast["win_rate"], "expectancy_r": fast["expectancy_r"]},
            "open": open_, "results": [{"ts": london(r["ts"]), "coin": r["coin"], "r": _f(r.get("r")), "usd": _f(r.get("amount_usd")),
                                        "note": r.get("note") or "", "tag": r.get("tag") or ""} for r in res],
            "paper_equity": float(rules.paper_equity)}


class Marks:
    """Log próprio do dashboard: equity ao vivo dos 4 bots a cada `every` s (para a curva comparativa)."""
    def __init__(self, path, every=300):
        self.path, self.every, self.last = path, every, 0.0; self.lock = threading.Lock()

    def maybe_add(self, eqs: dict, now=None):
        now = now or time.time()
        with self.lock:
            if now - self.last < self.every or not any(v is not None for v in eqs.values()): return
            self.last = now
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a") as f: f.write(json.dumps({"t": int(now), **{k: (round(v, 4) if v is not None else None) for k, v in eqs.items()}}) + "\n")
            except OSError:
                pass

    def read(self, limit=5000):
        try:
            with open(self.path) as f: lines = f.readlines()[-limit:]
        except OSError:
            return []
        out = []
        for ln in lines:
            try: out.append(json.loads(ln))
            except ValueError: pass
        return out


def _merge_curve(*series):
    m = {}
    for s in series:
        for t, v in s:
            if t and v is not None: m[int(t)] = round(float(v), 4)
    return [[t, m[t]] for t in sorted(m)]


def live_snapshot(prices: Prices, marks: Marks | None = None, now=None) -> dict:
    from desk import health
    from desk.rules import load_rules
    now = now or time.time()
    rules = load_rules(); rep = health.report()
    mode = rep.get("execution_mode")
    ceil, reset = float(rep.get("ceiling") or 1000.0), float(rep.get("reset_balance") or START)
    ex_dir = os.path.join(_state_dir(), f"exec_{mode}") if mode in ("paper_autonomous",) else None
    # símbolos precisos para preços
    syms = {"BTC-USD", "ETH-USD"}
    if ex_dir:
        st = _json(os.path.join(ex_dir, "state.json"), {}) or {}
        syms |= {p["symbol"] for p in (st.get("positions") or {}).values() if p.get("status") == "OPEN" and p.get("symbol")}
        bal = (_json(os.path.join(ex_dir, "paper_exchange.json"), {}) or {}).get("bal") or {}
        syms |= {f"{c}-USD" for c in bal if c != "USD"}
    from desk import store
    syms |= {p["coin"] for p in store.read("positions.csv") if p.get("status") == "OPEN" and re.match(r"^[A-Z0-9]{1,15}-USD$", p.get("coin", ""))}
    P = prices.get(syms); px = P["px"]
    bots, eqs, mk = [], {}, (marks.read() if marks else [])
    for key, meta in BOT_META.items():
        h = (rep.get("bots") or {}).get(key)
        if key == "D_executor":
            if not ex_dir:
                bots.append({"key": key, **meta, "available": False, "state": f"modo {mode} (sem executor paper)"}); continue
            v = executor_view(mode, px)
        else:
            v = c3_view(key.split("_", 1)[1], px)
        eq = v["equity_live"] if v["equity_live"] is not None else (h or {}).get("equity")
        peak = max(_f(v.get("peak"), START) or START, eq or 0)
        curve = _merge_curve(v.pop("curve"), [(m["t"], m.get(key)) for m in mk])
        eqs[key] = eq
        h = h or {}
        bots.append({"key": key, **meta, "available": True, "paper": True,
                     "state": h.get("state", "?"), "equity": eq, "start": START,
                     "pnl": (eq - START) if eq is not None else None, "pnl_pct": (eq / START - 1) if eq is not None else None,
                     "drawdown": ((peak - eq) / peak) if (eq is not None and peak) else None,
                     "ceiling": ceil, "to_ceiling": (ceil - eq) if eq is not None else None,
                     "ceiling_progress": (eq / ceil) if (eq is not None and ceil) else None,
                     "ceiling_latched": bool(h.get("ceiling_latched")), "killed": bool(h.get("kill_latched")),
                     "positions": v["positions"], "recent": v["recent"], "signal": v.get("signal"),
                     "criteria": _crit_view(h.get("criteria")), "any_tripped": any(c.get("tripped") and not c.get("informational")
                                                                                   for c in (h.get("criteria") or {}).values() if isinstance(c, dict)),
                     "last_run": london(h.get("last_run")), "curve": curve + ([[int(now), round(eq, 4)]] if eq is not None else [])})
    if marks: marks.maybe_add(eqs, now)
    try: bots += scalp_cards(now)
    except Exception as e: bots.append({"key": "S_scalp", "name": "Bots Scalp (SIMULADO)", "available": False, "state": _clean(f"erro: {type(e).__name__}")})
    try: desk = desk_view(rules)
    except Exception as e: desk = {"error": _clean(f"{type(e).__name__}: {e}")}
    return {"simulated": True, "banner": "SIMULADO — nenhuma ordem real", "execution_mode": mode,
            "live_orders": False, "now_london": datetime.fromtimestamp(now, LONDON).strftime("%d/%m/%Y %H:%M:%S"),
            "ceiling": ceil, "reset_balance": reset, "prices": {"px": px, "error": P["error"], "stale": P["stale"],
                                                                "age_s": P["age_s"], "updated": P["updated"]},
            "bots": bots, "desk": desk}
