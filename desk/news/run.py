"""Runner FORWARD dos livros NEWS (PAPER ONLY) → desk/state/news_paper/forward/.
Ciclo próprio de ~120 s (tools/news_up.sh --loop; o --ensure é chamado também por tools/scalp_up.sh --ensure), com o mesmo
limitador público 1 req/s partilhado (desk/scalp/feed) para a Revolut X. Sem broker, sem caminho real, sem chaves; não lê nem muda
o modo de execução do desk; não escreve journal/positions do desk; não emite alertas no outbox (o boletim lê `python -m desk.news status`).
Notícias só são negociadas AO VIVO: itens com mais de 90 min, ou já publicados quando o bot arrancou, nunca entram.
Auditoria: news_items.jsonl (cada notícia e a decisão) e signals.jsonl (cada avaliação moeda×livro com métricas e motivo).
"""
from __future__ import annotations
import csv, json, math, os, time
from datetime import datetime, timezone
from decimal import Decimal

from desk import store
from desk.scalp import feed
from . import spec as SP, sources as SRC
from .engine import Engine, new_state, new_book, to_json, from_json, BOOKS, BK, M1, TRAINING, START, CEIL, DD_KILL
from .spec import SPEC

NLP, UNI, SRCS, MK = SPEC["nlp"], SPEC["universe"], SPEC["sources"], SPEC["market"]
M5 = 5 * M1
GRACE = 20_000
CYCLE_S = 120
TRADE_COLS = ["book", "symbol", "entry_kind", "signal_ts", "fill_ts", "exit_ts", "entry", "stop", "tp", "stop_pct", "qty", "notional",
              "exit", "reason", "fee", "slip_cost", "pnl", "r_unit", "r", "news_score", "news"]
STR_COLS = {"book", "symbol", "entry_kind", "reason", "news"}


def base_dir():
    d = os.environ.get("NEWS_STATE_DIR") or os.path.join(store.STATE, "news_paper"); os.makedirs(d, exist_ok=True); return d


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


def _jsonl(p, rows):
    if not rows: return
    with open(p, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _tail_jsonl(p, n):
    if not os.path.exists(p): return []
    with open(p) as f: lines = f.readlines()[-n:]
    out = []
    for l in lines:
        try: out.append(json.loads(l))
        except ValueError: pass
    return out


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
            r[k] = float(r[k]) if r.get(k) not in ("", None) else None
        out.append(r)
    return out


def read_equity(d=None):
    p = os.path.join(d or fdir(), "equity.csv")
    if not os.path.exists(p): return []
    return [{k: (int(v) if k == "ts" else float(v)) for k, v in r.items() if v not in ("", None)} for r in csv.DictReader(open(p))]


# ---------------- mercado público Revolut X ----------------
def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def universe(tickers_json):
    """{BASE: {sym, bid, ask, mid, hs, spread_bps, qv24}} — UK, USD, fora das stables, com liquidez e spread dentro do spec."""
    out = {}
    for x in (tickers_json or {}).get("data") or []:
        s = str(x.get("symbol") or "")
        if x.get("region") != "UK" or not s.endswith("/USD"): continue
        base = s.split("/")[0].upper()
        if base in UNI["exclude_stables"]: continue
        bid, ask, mid, qv = _f(x.get("bid")), _f(x.get("ask")), _f(x.get("mid")), _f(x.get("quote_volume_24h"))
        if not (0 < bid < ask) or mid <= 0: continue
        sp = (ask - bid) / mid * 1e4
        out[base] = {"sym": f"{base}-USD", "bid": bid, "ask": ask, "mid": mid, "hs": (ask - bid) / 2 / mid, "spread_bps": sp, "qv24": qv,
                     "liquid": qv >= UNI["min_quote_vol_24h_usd"] and sp <= UNI["max_spread_bps"]}
    return out


def candles(sym, interval, since, until, get=feed.http_get):
    j = get(f"{feed.RX1}/public/candles/{sym}", {"interval": interval, "since": since, "until": until})
    if j is None or "data" not in j: return None
    out = {}
    for r in j["data"]:
        try:
            s = int(r["start"]); x = {"ts": s, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": float(r["volume"])}
        except (KeyError, TypeError, ValueError): continue
        if since <= s <= until and x["c"] > 0 and x["l"] > 0 and x["h"] >= x["l"]: out[s] = x
    return [out[k] for k in sorted(out)]


def features(bars5, now, pub_ms):
    """Features da confirmação de mercado a partir de velas 5m FECHADAS (start + 5m ≤ now − grace)."""
    B = [b for b in bars5 if b["ts"] + M5 <= now - GRACE]
    if len(B) < MK["min_bars"]: return {"ok": False, "why": f"dados insuficientes ({len(B)} velas 5m < {MK['min_bars']})"}
    c = B[-1]["c"]; prior = [b["v"] for b in B[:-3]]
    base = sum(prior) / len(prior) if prior else 0.0
    vr = (sum(b["v"] for b in B[-3:]) / (3 * base)) if base > 0 else None
    mom = c / B[-4]["c"] - 1
    chg = c / B[0]["c"] - 1
    n = MK["atr_n"]; trs = []
    for i in range(len(B) - n, len(B)):
        pc = B[i - 1]["c"]; trs.append(max(B[i]["h"] - B[i]["l"], abs(B[i]["h"] - pc), abs(B[i]["l"] - pc)))
    atr = sum(trs) / n / c
    runup = None
    if pub_ms:
        ref = next((b for b in B if b["ts"] <= pub_ms < b["ts"] + M5), None) or next((b for b in B if b["ts"] >= pub_ms), None)
        if ref is None and pub_ms < B[0]["ts"]: ref = B[0]
        runup = c / ref["o"] - 1 if ref else 0.0
    return {"ok": True, "close": c, "vol_ratio": vr, "mom_15m": mom, "chg_24h": chg, "atr_pct": atr, "runup": runup,
            "last_5m": iso(B[-1]["ts"]), "bars": len(B)}


# ---------------- macro ponto-no-tempo (mesma regra dos livros EMS) ----------------
def _macro_factory():
    try:
        from desk.ems.run import Macro
        return Macro()
    except Exception:
        return lambda ts: None


# ---------------- FORWARD ----------------
class Forward:
    def __init__(self, get=feed.http_get, get_text=SRC.get_text, clock=lambda: int(time.time() * 1000), log=print, macro=None):
        self.get, self.get_text, self.clock, self.log = get, get_text, clock, log
        self.d = fdir(); self.p = os.path.join(self.d, "state.json"); self.meta_p = os.path.join(self.d, "meta.json")
        self.macro = macro
        self.meta = _load(self.meta_p, None) or {"health": {"ok_runs": 0, "fail_runs": 0, "consec_fail": 0, "last_ok_ts": None,
                                                            "first_ts": None, "last_error": None},
                                                 "seen": {}, "polled": {}, "baseline_done": False, "active": [], "veto": {},
                                                 "trending": [], "trending_ts": None, "source_errors": {}, "events": [],
                                                 "n_events_total": 0, "rebases": [], "counts": {}}

    def _names(self, now):
        p = os.path.join(self.d, "names.json"); c = _load(p, {}) or {}
        if c.get("map") and now - c.get("ts", 0) < SRCS["poll_s"]["names"] * 1000: return c["map"]
        m = SRC.fetch_names(self.get_text)
        if m: _atomic_json(p, {"ts": now, "map": m}); return m
        return c.get("map") or {}

    def _due(self, now):
        return {g for g, s in SRCS["poll_s"].items() if g in ("rss", "listings", "trending") and now - (self.meta["polled"].get(g) or 0) >= s * 1000}

    def ingest(self, now, uni):
        """Lê fontes devidas, regista CADA item novo com a decisão. Devolve n novos."""
        due = self._due(now)
        if not due: return 0
        items, trending, errs = SRC.fetch_all(due, SRCS, self.get_text)
        for g in due: self.meta["polled"][g] = now
        self.meta["source_errors"] = {**{k: v for k, v in self.meta.get("source_errors", {}).items() if k not in errs}, **{k: iso(now) for k in errs}}
        if trending is not None: self.meta["trending"] = [t for t in trending if t in uni]; self.meta["trending_ts"] = now
        names = self._names(now) if items else {}
        U = set(uni); log, new = [], 0
        baseline = not self.meta.get("baseline_done")
        for it in items:
            if it["id"] in self.meta["seen"]: continue
            self.meta["seen"][it["id"]] = now; new += 1
            sc = SRC.score_item(it, U, names, NLP)
            pub = it.get("pub_ms") or now
            age_min = (now - pub) / 60000
            rec = {"t": iso(now), "id": it["id"], "source": it["source"], "kind": it["kind"], "pub": iso(pub), "age_min": round(age_min, 1),
                   "title": it["title"], "coins": sc["coins"], "scores": sc["scores"], "pos": sc["pos_terms"], "neg": sc["neg_terms"]}
            if baseline: rec["decision"] = "baseline_on_start (já publicado quando o bot arrancou — nunca negociado)"
            elif not sc["coins"]: rec["decision"] = "ignorada: nenhuma moeda do universo Revolut X"
            elif age_min > NLP["item_max_age_min"]: rec["decision"] = f"ignorada: velha ({age_min:.0f} min > {NLP['item_max_age_min']})"
            else:
                parts = []
                for c, s in sc["scores"].items():
                    if s <= NLP["negative_veto_max"]:
                        self.meta["veto"][c] = now + NLP["negative_veto_h"] * 3_600_000; parts.append(f"{c}: negativa {s} → veto 6 h")
                    elif s >= NLP["positive_min"]:
                        self.meta["active"].append({"id": it["id"], "sym": c, "score": s, "pub": pub, "seen": now, "title": it["title"][:160], "source": it["source"]})
                        parts.append(f"{c}: positiva +{s} → candidata (janela 60 min)")
                    else: parts.append(f"{c}: neutra ({s})")
                rec["decision"] = "; ".join(parts)
            k = rec["decision"].split(":")[0].split(" (")[0]
            self.meta["counts"][k] = self.meta["counts"].get(k, 0) + 1
            log.append(rec)
        if baseline and "rss" in due: self.meta["baseline_done"] = True
        _jsonl(os.path.join(self.d, "news_items.jsonl"), log)
        cut = now - 3 * 86_400_000
        self.meta["seen"] = {k: v for k, v in self.meta["seen"].items() if v >= cut}
        return new

    def candidates(self, now, uni):
        win = NLP["window_min"] * M1
        self.meta["active"] = [a for a in self.meta["active"] if now - max(a["pub"], a["seen"] - 10 * M1) <= win]
        self.meta["veto"] = {k: v for k, v in self.meta["veto"].items() if v > now}
        agg = {}
        for a in self.meta["active"]:
            g = agg.setdefault(a["sym"], {"score": 0, "ids": [], "pub": a["pub"], "titles": []})
            g["score"] += a["score"]; g["ids"].append(a["id"]); g["pub"] = min(g["pub"], a["pub"]); g["titles"].append(a["title"])
        for s, g in agg.items():
            if s in self.meta.get("trending", []): g["score"] += NLP["trending_bonus"]; g["trending"] = True
        return sorted(agg.items(), key=lambda kv: -kv[1]["score"])[:NLP["max_candidates_per_cycle"]]

    def run_once(self):
        now = self.clock(); h = self.meta["health"]; h["first_ts"] = h["first_ts"] or now
        trades, events, sigs = [], [], []
        try:
            SP.check()
            raw = _load(self.p)
            st = from_json(raw) if raw else new_state(trade_from=now)
            if not raw: st["forward_start"] = now; st["prereg_sha256"] = SP.check(); st["code_sha256"] = SP.code_hash()
            eng = Engine(st, on_trade=trades.append, on_event=events.append)
            uni = universe(self.get(f"{feed.RX1}/public/tickers"))
            if not uni: raise RuntimeError("tickers públicos indisponíveis")
            self.meta["universe_n"] = len(uni); self.meta["liquid_n"] = sum(1 for u in uni.values() if u["liquid"])
            self.ingest(now, uni)
            # 1) gerir posições/pendentes com velas 1m fechadas
            last_closed = (now - M1 - GRACE) // M1 * M1
            syms = sorted({s for b in st["books"].values() for s in list(b["pos"]) + list(b["pend"])})
            for s in syms:
                frm = st["last_bar"].get(s)
                frm = frm + M1 if frm is not None else min([b["pend"][s]["active_from"] for b in st["books"].values() if s in b["pend"]] or
                                                           [b["pos"][s]["fill_ts"] + M1 for b in st["books"].values() if s in b["pos"]])
                if frm > last_closed: continue
                base = s.split("-")[0]; hs = uni.get(base, {}).get("hs")
                rows, ok = feed.candles_1m(s, frm, last_closed, self.get)
                if not ok: continue
                g, _ = feed.grid(rows, frm, last_closed, float(st["last_close"][s]) if s in st["last_close"] else (rows[0]["o"] if rows else None))
                for r in g: eng.bar(s, r["ts"], r["o"], r["h"], r["l"], r["c"], hs)
            # 2) candidatas de notícia → confirmação de mercado → livros
            macro = (self.macro or _macro_factory())(now)
            for base, g in self.candidates(now, uni):
                u = uni.get(base); rec = {"t": iso(now), "coin": base, "news_score": g["score"], "news_ids": g["ids"], "trending": bool(g.get("trending")),
                                          "headline": g["titles"][0]}
                if base in self.meta["veto"]: rec["decision"] = "rejeitada: veto por notícia negativa recente"; sigs.append(rec); continue
                if not u or not u["liquid"]:
                    rec["decision"] = f"rejeitada: ilíquida/spread (vol24h ${u['qv24']:,.0f}, spread {u['spread_bps']:.0f} bps)" if u else "rejeitada: fora do universo"
                    sigs.append(rec); continue
                bars = candles(u["sym"], 5, (now // M5) * M5 - 289 * M5, (now // M5) * M5, self.get)
                if bars is None: rec["decision"] = "rejeitada: velas 5m indisponíveis"; sigs.append(rec); continue
                f = features(bars, now, g["pub"])
                rec.update({k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items() if k != "ok"}, spread_bps=round(u["spread_bps"], 1), macro=macro)
                if not f["ok"]: rec["decision"] = "rejeitada: " + f["why"]; sigs.append(rec); continue
                f.update(news_score=g["score"], news_ids=g["ids"])
                rec["books"] = {}
                for name in BOOKS:
                    acc, why = eng.evaluate(name, u["sym"], f, now, u["hs"], macro)
                    rec["books"][name] = ("ACEITE: " if acc else "rejeitada: ") + why
                    if acc: self.log(f"NEWS {name} {u['sym']} {why} · score {g['score']} · {g['titles'][0][:90]}")
                sigs.append(rec)
            # 3) marcação
            prices = {u["sym"]: u["mid"] for u in uni.values()}
            eng.mark(now, prices)
            append_csv(os.path.join(self.d, "equity.csv"), ["ts"] + BOOKS, [{"ts": now, **{b: round(float(st["books"][b]["equity"]), 4) for b in BOOKS}}])
            append_csv(os.path.join(self.d, "trades.csv"), TRADE_COLS, trades)
            _jsonl(os.path.join(self.d, "signals.jsonl"), sigs)
            self.meta["events"] = (self.meta["events"] + events)[-200:]
            self.meta["n_events_total"] = self.meta.get("n_events_total", 0) + len(events)
            _atomic_json(self.p, to_json(st))
            h.update(ok_runs=h["ok_runs"] + 1, consec_fail=0, last_ok_ts=now, last_error=None)
            res = {"ok": True, "candidates": len(sigs), "trades_closed": len(trades), "active_news": len(self.meta["active"])}
        except Exception as e:
            h.update(fail_runs=h["fail_runs"] + 1, consec_fail=h["consec_fail"] + 1, last_error=f"{type(e).__name__}: {e}"[:200])
            res = {"ok": False, "error": h["last_error"]}
        self.meta["last_run"] = now
        _atomic_json(self.meta_p, self.meta)
        return res


def loop(every=CYCLE_S, log=print):
    f = Forward(log=log)
    while True:
        t = time.time(); r = f.run_once(); log(json.dumps({"t": iso(int(t * 1000)), "news": r}))
        time.sleep(max(10.0, every - (time.time() - t)))


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
def metrics(trades, bs):
    A = SPEC["auditor"]; n = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]; losses = [-t["pnl"] for t in trades if t["pnl"] <= 0]
    exp = sum(t["r"] for t in trades) / n if n else None; wr = len(wins) / n if n else None
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else (None if not wins else math.inf)
    dd = float((bs or {}).get("max_dd", 0.0))
    if n < A["min_trades"]: verdict = "NO-GO (DD>20% já com poucos trades)" if dd > A["max_dd"] else "dados insuficientes"
    elif wr >= A["win_rate"] and exp >= A["expectancy_r"] and dd <= A["max_dd"]: verdict = "possível GO (só paper)"
    else: verdict = "NO-GO"
    return {"trades": n, "win_rate": wr, "expectancy_r": exp, "profit_factor": pf, "max_dd": dd, "pnl": sum(t["pnl"] for t in trades),
            "fees": sum(t["fee"] for t in trades), "slippage_spread": sum(t["slip_cost"] for t in trades), "verdict": verdict}


def report(st=None, d=None):
    d = d or fdir(); st = st if st is not None else (_load(os.path.join(d, "state.json"), {}) or {})
    T = read_trades(d); out = {}
    for b in BOOKS:
        bs = (st.get("books") or {}).get(b, {}) or {}
        m = metrics([t for t in T if t["book"] == b], bs)
        eq = float(bs["equity"]) if bs.get("equity") is not None else None
        peak = float(bs["peak"]) if bs.get("peak") is not None else None
        m.update(name=BK[b]["name"], state=bs.get("state", TRAINING), equity=eq, peak=peak, cycles=bs.get("cycles", 0),
                 drawdown_now=(1 - eq / peak) if eq and peak else 0.0, open=len(bs.get("pos") or {}), pending=len(bs.get("pend") or {}),
                 counts=bs.get("n"), ceiling_progress=(eq / float(CEIL)) if eq else 0.0)
        m["dd_room"] = float(DD_KILL) - m["drawdown_now"]
        out[b] = m
    return out


def _pidalive():
    pidf = os.path.join(feed.ROOT, "logs", "run", "news.pid")
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
    now = int(time.time() * 1000); since = now - 24 * 3_600_000
    items = [r for r in _tail_jsonl(os.path.join(d, "news_items.jsonl"), 3000) if r.get("t") and r["t"] >= iso(since)]
    sigs = [r for r in _tail_jsonl(os.path.join(d, "signals.jsonl"), 3000) if r.get("t") and r["t"] >= iso(since)]
    acc = [r for r in sigs if any(str(v).startswith("ACEITE") for v in (r.get("books") or {}).values())]
    out["forward"] = {"loop_running": alive, "pid": pid if alive else None, "started": iso(st.get("forward_start")),
                      "last_run": iso(meta.get("last_run")), "health": meta.get("health"), "universe_n": meta.get("universe_n"),
                      "liquid_n": meta.get("liquid_n"), "source_errors": meta.get("source_errors"), "trending": meta.get("trending"),
                      "news_24h": len(items), "news_with_coin_24h": sum(1 for r in items if r.get("coins")),
                      "positive_24h": sum(1 for r in items if "positiva" in str(r.get("decision"))),
                      "candidate_evals_24h": len(sigs), "accepted_24h": len(acc),
                      "active": [{"coin": a["sym"], "score": a["score"], "title": a["title"], "source": a["source"]} for a in meta.get("active", [])][:10],
                      "veto": sorted((meta.get("veto") or {}).keys()),
                      "last_signals": sigs[-5:], "events": (meta.get("events") or [])[-10:],
                      "books": report(st, d) if st else {}}
    return out


def _usd(x): return f"${x:,.2f}" if x is not None else "—"


def fmt_status(s):
    f = s["forward"]
    L = [f"NEWS books · {s['spec_id']} · PAPER ONLY · prereg {str(s.get('prereg_sha256', s.get('prereg_error')))[:12]}",
         f"FORWARD: loop {'A CORRER pid ' + str(f['pid']) if f['loop_running'] else 'PARADO'} · início {f['started']} · último ciclo "
         f"{f['last_run']} · falhas seguidas {(f.get('health') or {}).get('consec_fail')} · universo {f.get('universe_n')} moedas ({f.get('liquid_n')} líquidas)",
         f"Notícias 24 h: {f['news_24h']} lidas · {f['news_with_coin_24h']} com moeda · {f['positive_24h']} positivas · "
         f"{f['candidate_evals_24h']} avaliações · {f['accepted_24h']} entradas aceites · trending: {', '.join(f.get('trending') or []) or '—'}"
         + (f" · veto: {', '.join(f['veto'])}" if f.get("veto") else "")
         + (f" · fontes com erro: {', '.join(f['source_errors'])}" if f.get("source_errors") else "")]
    for b, m in (f["books"] or {}).items():
        wr = f"{100 * m['win_rate']:.0f}%" if m["win_rate"] is not None else "—"
        ex = f"{m['expectancy_r']:+.2f}R" if m["expectancy_r"] is not None else "—"
        L.append(f"  {b:<14} n={m['trades']:<3}/40 WR {wr:<4} {ex:<7} DD {100 * m['max_dd']:.1f}% (agora {100 * m['drawdown_now']:.1f}%) "
                 f"eq {_usd(m['equity'])} abertas {m['open']} pend {m['pending']} {m['state']} → {m['verdict']}")
    for a in f.get("active") or []:
        L.append(f"  📰 {a['coin']} +{a['score']} [{a['source']}] {a['title'][:110]}")
    for r in f.get("last_signals") or []:
        L.append(f"  🔎 {r['t'][11:16]}Z {r['coin']} score {r['news_score']}: " + (r.get("decision") or " | ".join(f"{k}: {v}" for k, v in (r.get("books") or {}).items())))
    for e in f.get("events") or []:
        L.append(f"  ⚠ {e.get('book')}: {e.get('type')} em {iso(e.get('ts'))} (equity {e.get('equity')})")
    return "\n".join(L)


# ---------------- dados para o painel (só leitura, sem segredos, sem links) ----------------
def dashboard_data(max_trades=40, max_items=30):
    d = fdir(); st = _load(os.path.join(d, "state.json"), {}) or {}; meta = _load(os.path.join(d, "meta.json"), {}) or {}
    if not st: return {"available": False, "why": "forward ainda não arrancou"}
    rep = report(st, d); T = read_trades(d)
    cards = []
    for b, m in rep.items():
        bs = st["books"][b]
        cards.append({"id": b, "name": m["name"], "state": m["state"], "equity": m["equity"], "start": float(START), "ceiling": float(CEIL),
                      "drawdown_now": m["drawdown_now"], "dd_limit": float(DD_KILL), "dd_room": m["dd_room"], "max_dd": m["max_dd"],
                      "trades": m["trades"], "need_trades": SPEC["auditor"]["min_trades"], "win_rate": m["win_rate"], "expectancy_r": m["expectancy_r"],
                      "profit_factor": m["profit_factor"] if m["profit_factor"] is None or math.isfinite(m["profit_factor"]) else None,
                      "pnl": m["pnl"], "fees": m["fees"] + m["slippage_spread"], "verdict": m["verdict"], "counts": m["counts"],
                      "rule": BK[b]["rule"],
                      "positions": [{"coin": s, "entry": float(p["entry"]), "stop": float(p["stop"]), "tp": float(p["tp"]), "qty": float(p["qty"]),
                                     "since": p["fill_ts"], "kind": p["kind"], "score": p.get("news_score")} for s, p in (bs.get("pos") or {}).items()],
                      "orders": [{"coin": s, "kind": q["kind"], "limit": float(q["limit"]) if q.get("limit") else None, "stop": float(q["stop"]),
                                  "tp": float(q["tp"]), "placed": q["signal_ts"], "expires": q["expiry"]} for s, q in (bs.get("pend") or {}).items()]})
    items = _tail_jsonl(os.path.join(d, "news_items.jsonl"), 400)
    items = [r for r in items if r.get("coins") or "positiva" in str(r.get("decision"))][-max_items:]
    news = [{"t": r["t"], "source": r["source"], "title": r["title"][:180], "coins": r.get("coins"), "scores": r.get("scores"),
             "decision": str(r.get("decision"))[:160]} for r in items]
    sigs = [{"t": r["t"], "coin": r["coin"], "score": r.get("news_score"), "vol_ratio": r.get("vol_ratio"), "mom_15m": r.get("mom_15m"),
             "runup": r.get("runup"), "chg_24h": r.get("chg_24h"), "spread_bps": r.get("spread_bps"),
             "decision": r.get("decision"), "books": r.get("books")} for r in _tail_jsonl(os.path.join(d, "signals.jsonl"), 25)]
    marks = [{"book": t["book"], "coin": t["symbol"], "fill": int(t["fill_ts"]), "exit": int(t["exit_ts"]), "entry": t["entry"], "exit_px": t["exit"],
              "stop": t["stop"], "tp": t["tp"], "r": t["r"], "pnl": t["pnl"], "reason": t["reason"], "kind": t["entry_kind"], "score": t["news_score"]}
             for t in T[-max_trades:]]
    E = read_equity(d)[-360:]
    return {"available": True, "spec_id": SPEC["id"], "started": st.get("forward_start"), "last_run": meta.get("last_run"),
            "universe_n": meta.get("universe_n"), "liquid_n": meta.get("liquid_n"), "trending": meta.get("trending") or [],
            "veto": sorted((meta.get("veto") or {}).keys()), "source_errors": sorted((meta.get("source_errors") or {}).keys()),
            "cards": cards, "news": list(reversed(news)), "signals": list(reversed(sigs)), "trades": marks,
            "curve": {b: [[r["ts"], r.get(b)] for r in E] for b in BOOKS},
            "rules": {"start": float(START), "ceiling": float(CEIL), "dd_kill": float(DD_KILL), "maker_fee": 0.0, "taker_fee": 0.0009,
                      "slippage": 0.001, "risk_pct": 0.01, "min_trades": 40, "window_min": NLP["window_min"], "max_age_min": NLP["item_max_age_min"]}}
