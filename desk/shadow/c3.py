"""C3 — tendência BTC+ETH com vol-target — OBSERVAÇÃO FORWARD EM PAPER, **NÃO VALIDADA** (tag c3_unvalidated).

Spec: desk/strategies/26_c3_trend_vt_unvalidated.md. REJEITADA pelo pré-registo (desk/research/prereg_estudo.json, falha V4–V7);
o utilizador aprovou explicitamente só esta observação simulada com dados reais, lado a lado com um B&H BTC.

Isolamento (garantido por construção e por testes):
  * NÃO existe broker aqui: nem LiveBroker nem PaperBroker; a "execução" é aritmética sobre preços públicos.
  * Só GET a endpoints PÚBLICOS (Revolut X /public/candles e /public/order-book; fallback Coinbase Exchange público). Sem chaves.
  * Estado próprio em desk/state/shadow_c3/ (state.json, trades.csv, equity.csv). Não escreve journal.csv/positions.csv
    → não conta para o GO do auditor nem é lido por live/executor. Não lê nem altera execution_mode.
  * Único ponto de contacto com o desk: notificações no outbox (tipo SHADOW_C3_*, autonomous, sem TAKEN/SKIPPED).

python -m desk.shadow.c3 run-once | status | resume [livro] | rebase <c3|c3_raw|bh_btc|all> --confirm
run-once é idempotente: cada vela diária fechada é processada uma única vez; chamadas repetidas no mesmo dia só re-marcam.
"""
from __future__ import annotations
import csv, json, math, os, sys, time
from datetime import datetime, timezone

import numpy as np
import requests

from desk import store, health as HL   # teto / critérios de morte partilhados (lê só target_balance, reset_balance, kill_*)

TAG = "c3_unvalidated"
LABEL = "NÃO VALIDADA / not validated"
D, H = 86_400_000, 3_600_000

# ---- parâmetros CONGELADOS (campeão IS C3_btc_eth_tendencia_vt:assets=BTC+ETH,n=100,vt=1; prereg sha256 8b9d3112…28baa1) ----
VARIANT_ID = "C3_btc_eth_tendencia_vt:assets=BTC+ETH,n=100,vt=1"
ASSETS = ("BTC", "ETH")
SMA_N = 100
VOL_N = 30
VOL_TARGET = 0.5                  # peso = (1/2) × min(1, 0.5 / vol30 anualizada (365, log-ret, ddof=0))
STOP = 0.08                       # −8% do preço médio (regra do desk)
REENTRY_D = 14                    # após stop: reentrada só com sinal 0 ou passados 14 dias
BAND_ABS, BAND_REL = 0.01, 0.20   # banda de rebalance
MIN_W = 0.005
DESK_CAP, MAX_POS = 0.125, 5      # 1% risco / 8% stop ⇒ 12,5% por posição; ≤5 posições
# ---- execução paper ----
TAKER = 0.0009                    # Revolut X taker; compra ao ASK, vende ao BID do order book ao vivo
FALLBACK_HALF_SPREAD = 0.001      # sem book: meio-spread assumido 10 bps sobre o último fecho
STOP_SLIP = 0.001                 # stop (simula tpsl no broker): preço do stop (ou abertura, se gap) − taker − 10 bps
START_EQUITY = 65.0
# ---- critérios de paragem automática (RELATORIO §3 e §7) ----
DD_PAUSE = {"c3": 0.14, "c3_raw": 0.20, "bh_btc": 0.20}   # 1,2× pior DD OOS com tetos (11,4%) ≈ 14% (mais estrito que 20%); sinal puro 20%
INFO_ONLY = {"bh_btc"}            # baseline de comparação: critérios/teto só AVISAM, nunca pausam
DATA_GAP_DAYS = 3                 # 3 dias seguidos sem velas válidas da Revolut X
SHARPE_WIN = 365                  # 12 meses forward com Sharpe < 0
DIVERGE_WIN, DIVERGE_MAX = 30, 0.02   # desvio > 2 p.p./30 dias entre paper e réplica do backtest nas mesmas velas

BOOKS = {"c3": "C3 (tetos do desk 12,5%)", "c3_raw": "C3 sinal puro (sem tetos)", "bh_btc": "B&H BTC (baseline)"}
RX = "https://revx.revolut.com/api/1.0"
CB = "https://api.exchange.coinbase.com"
BROKER = None                     # deliberado: este módulo nunca tem broker


def _assert_paper_only():
    if BROKER is not None: raise RuntimeError("shadow C3 é paper-only: BROKER tem de ser None")
    for name, v in list(globals().items()):
        mod = getattr(v, "__module__", None) or getattr(v, "__name__", "")
        if isinstance(mod, str) and (mod == "live" or mod.startswith("live.") or mod.startswith("bot.revolutx")):
            raise RuntimeError(f"shadow C3 não pode referenciar {name} ({mod})")


def state_dir():
    d = os.environ.get("C3_STATE_DIR") or os.path.join(store.STATE, "shadow_c3"); os.makedirs(d, exist_ok=True); return d


def _p(name): return os.path.join(state_dir(), name)


def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------- dados públicos ----------------
def http_get(url, params=None, tries=3, pause=1.05):
    """GET público com 1 req/s (Revolut X) e retry em 5xx/429/timeout. Devolve JSON ou None."""
    for k in range(tries):
        time.sleep(pause)
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200: return r.json()
            if r.status_code < 500 and r.status_code != 429: return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 ** k)
    return None


def _closed(rows, now_ms):
    rows = sorted(rows, key=lambda r: r["start"])
    return [r for i, r in enumerate(rows) if i < len(rows) - 1 or r["start_raw"] + 25 * H <= now_ms]


def candles_revx(sym, now_ms, get=http_get):
    j = get(f"{RX}/public/candles/{sym}-USD", {"interval": 1440})
    if not j or not j.get("data"): return None
    rows = []
    for r in j["data"]:
        try:
            s = int(r["start"]); x = {k: float(r[k]) for k in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError):
            continue
        if x["close"] > 0: rows.append({"start": (s + 12 * H) // D * D, "start_raw": s, **x})   # dia de Londres → data
    return _closed(rows, now_ms) or None


def candles_coinbase(sym, now_ms, get=http_get):
    j = get(f"{CB}/products/{sym}-USD/candles", {"granularity": 86400}, pause=0.2)
    if not isinstance(j, list) or not j: return None
    rows = [{"start": int(r[0]) * 1000, "start_raw": int(r[0]) * 1000, "low": float(r[1]), "high": float(r[2]),
             "open": float(r[3]), "close": float(r[4])} for r in j if len(r) >= 5 and float(r[4]) > 0]
    return _closed(rows, now_ms) or None


def book_revx(sym, get=http_get):
    j = get(f"{RX}/public/order-book/{sym}-USD")
    d = (j or {}).get("data", j) or {}
    try: return {"bid": float(d["bids"][0]["p"]), "ask": float(d["asks"][0]["p"]), "src": "revx_book"}
    except (KeyError, IndexError, TypeError, ValueError): return None


def book_coinbase(sym, get=http_get):
    j = get(f"{CB}/products/{sym}-USD/book", {"level": 1}, pause=0.2)
    try: return {"bid": float(j["bids"][0][0]), "ask": float(j["asks"][0][0]), "src": "coinbase_book"}
    except (KeyError, IndexError, TypeError, ValueError): return None


def fetch_market(now_ms, get=http_get):
    """Velas 1D fechadas de BTC e ETH da MESMA fonte (Revolut X; se falhar, Coinbase) + topo de livro para execução."""
    src, cs = "revx", {}
    for s in ASSETS:
        c = candles_revx(s, now_ms, get)
        if not c: src = None; break
        cs[s] = c
    if src is None:
        src, cs = "coinbase", {}
        for s in ASSETS:
            c = candles_coinbase(s, now_ms, get)
            if not c: return None
            cs[s] = c
    books = {}
    for s in ASSETS:
        b = book_revx(s, get) or book_coinbase(s, get)
        if not b:
            last = cs[s][-1]["close"]
            b = {"bid": last * (1 - FALLBACK_HALF_SPREAD), "ask": last * (1 + FALLBACK_HALF_SPREAD), "src": "assumed_10bps_on_close"}
        books[s] = b
    return {"source": src, "candles": cs, "books": books}


# ---------------- sinal (idêntico a desk.research.estudo.s_trend + desk_caps) ----------------
def target_weights(closes: dict, caps: bool) -> dict:
    out = {}
    for s in ASSETS:
        c = np.asarray(closes[s], float)
        if len(c) < max(SMA_N, VOL_N + 1):
            out[s] = {"w": 0.0, "on": None, "sma": None, "vol": None, "why": "INSUFFICIENT_DATA"}; continue
        sma = float(c[-SMA_N:].mean()); lr = np.diff(np.log(c[-(VOL_N + 1):])); vol = float(lr.std() * math.sqrt(365))
        on = bool(c[-1] > sma)
        w = (1.0 / len(ASSETS)) * min(1.0, VOL_TARGET / vol) if (on and vol > 0) else 0.0
        if caps: w = min(w, DESK_CAP)
        out[s] = {"w": w, "on": on, "sma": sma, "vol": vol, "close": float(c[-1])}
    if caps:   # ≤ MAX_POS posições (só 2 activos: nunca vinculativo, mas mantido para fidelidade a desk_caps)
        keep = sorted((s for s in out if out[s]["w"] > 0), key=lambda s: -out[s]["w"])[:MAX_POS]
        for s in out:
            if s not in keep: out[s]["w"] = 0.0
    return out


# ---------------- estado ----------------
def new_book(cash=START_EQUITY):
    return {"cash": float(cash), "units": {s: 0.0 for s in ASSETS}, "avg": {s: 0.0 for s in ASSETS},
            "blocked": {s: False for s in ASSETS}, "stop_day": {s: None for s in ASSETS}, "entry_day": {s: None for s in ASSETS},
            "peak": float(cash), "paused": None, "equity": float(cash)}


def load_state():
    p = _p("state.json")
    if os.path.exists(p): return json.load(open(p))
    return {"tag": TAG, "label": LABEL, "variant": VARIANT_ID, "created_at": None, "start_bar": None, "last_bar": None,
            "last_revx_bar": None, "paused": None, "books": {k: new_book() for k in BOOKS}, "last_run": None, "runs": 0}


def save_state(st):
    p = _p("state.json"); tmp = p + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1, default=float); os.replace(tmp, p)


TRADE_COLS = ["ts", "bar", "book", "coin", "side", "reason", "qty", "price", "fee_usd", "notional_usd", "w_target", "w_before",
              "equity", "source", "px_src", "tag"]
EQ_COLS = ["bar", "ts", "source", "c3", "c3_raw", "bh_btc", "c3_dd", "c3_raw_dd", "bh_dd", "c3_expo", "c3_raw_expo",
           "btc_close", "eth_close", "paused", "tag"]


def _append(name, cols, rows):
    if not rows: return
    p = _p(name); new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new: w.writeheader()
        for r in rows: w.writerow({**{k: "" for k in cols}, **r, "tag": TAG})


def _read(name):
    p = _p(name)
    return list(csv.DictReader(open(p, newline=""))) if os.path.exists(p) else []


# ---------------- motor paper ----------------
def _equity(b, px): return b["cash"] + sum(b["units"][s] * px[s] for s in ASSETS)


def _sell(b, s, q, price, ctx, reason, cost=TAKER):
    got = q * price * (1 - cost); b["cash"] += got; b["units"][s] -= q
    if b["units"][s] <= 1e-15: b["units"][s] = 0.0; b["avg"][s] = 0.0; b["entry_day"][s] = None
    return {**ctx, "coin": s, "side": "SELL", "reason": reason, "qty": f"{q:.8f}", "price": f"{price:.6f}",
            "fee_usd": f"{q * price * cost:.4f}", "notional_usd": f"{q * price:.4f}"}


def _buy(b, s, q, price, ctx, reason):
    spend = q * price * (1 + TAKER)
    if spend > b["cash"]: q *= b["cash"] / spend; spend = b["cash"]
    if q <= 0: return None
    b["avg"][s] = (b["avg"][s] * b["units"][s] + price * q) / (b["units"][s] + q)
    if b["units"][s] == 0: b["entry_day"][s] = ctx["bar"]
    b["cash"] -= spend; b["units"][s] += q
    return {**ctx, "coin": s, "side": "BUY", "reason": reason, "qty": f"{q:.8f}", "price": f"{price:.6f}",
            "fee_usd": f"{q * price * TAKER:.4f}", "notional_usd": f"{q * price:.4f}"}


def check_stops(b, bars_by_asset, ctx):
    """Stop −8% do preço médio em cada vela fechada nova (simula tpsl resting): sai ao stop, ou à abertura se houve gap."""
    out = []
    for s in ASSETS:
        for bar in bars_by_asset[s]:
            if b["units"][s] <= 0 or not b["entry_day"][s] or day(bar["start"]) < b["entry_day"][s]: continue
            sp = b["avg"][s] * (1 - STOP)
            if bar["low"] <= sp:
                px = min(bar["open"], sp); bd = day(bar["start"])
                out.append(_sell(b, s, b["units"][s], px, {**ctx, "bar": bd}, "STOP_8PCT" + ("_GAP" if bar["open"] < sp else ""),
                                 cost=TAKER + STOP_SLIP))
                b["blocked"][s] = True; b["stop_day"][s] = bd
    return out


def rebalance(b, W, books, ctx):
    """Igual ao motor do estudo: vendas primeiro (saída/redução acima da banda), depois compras até ao alvo. Preço: BID/ASK ao vivo."""
    mid = {s: (books[s]["bid"] + books[s]["ask"]) / 2 for s in ASSETS}; E = _equity(b, mid); out = []
    for s in ASSETS:
        w = W[s]["w"]
        if b["blocked"][s] and (w <= 0 or (b["stop_day"][s] and
                                          (datetime.fromisoformat(ctx["bar"]) - datetime.fromisoformat(b["stop_day"][s])).days >= REENTRY_D)):
            b["blocked"][s] = False
    for s in ASSETS:
        if b["units"][s] > 0:
            w = W[s]["w"]; tgt = 0.0 if (b["blocked"][s] or w <= 0) else w; cur = b["units"][s] * mid[s] / E
            if tgt == 0.0 or cur - tgt > max(BAND_ABS, BAND_REL * cur):
                q = b["units"][s] if tgt == 0.0 else b["units"][s] - tgt * E / mid[s]
                r = _sell(b, s, q, books[s]["bid"], {**ctx, "w_target": f"{tgt:.4f}", "w_before": f"{cur:.4f}", "px_src": books[s]["src"]},
                          "EXIT_SIGNAL" if tgt == 0.0 else "REBALANCE_DOWN")
                out.append(r)
    for s in ASSETS:
        w = W[s]["w"]
        if b["blocked"][s] or w < MIN_W: continue
        cur = b["units"][s] * mid[s] / E
        if b["units"][s] == 0 or w - cur > max(BAND_ABS, BAND_REL * w):
            q = (w * E - b["units"][s] * mid[s]) / books[s]["ask"]
            if q <= 0: continue
            r = _buy(b, s, q, books[s]["ask"], {**ctx, "w_target": f"{w:.4f}", "w_before": f"{cur:.4f}", "px_src": books[s]["src"]},
                     "ENTER" if b["units"][s] == 0 else "REBALANCE_UP")
            if r: out.append(r)
    return out


def replica_equity(candles, start_bar, caps):
    """Réplica do backtest (desk.research.estudo.run_sim, custos base) nas MESMAS velas, desde o início forward."""
    from desk.research import estudo as E
    days = sorted(set.intersection(*[{r["start"] for r in candles[s]} for s in ASSETS]))
    ts = np.array(days, dtype=np.int64); T = len(ts)
    P = {"ts": ts, "syms": list(ASSETS)}
    by = {s: {r["start"]: r for r in candles[s]} for s in ASSETS}
    for k in ("open", "high", "low", "close"): P[k] = np.array([[by[s][t][k] for s in ASSETS] for t in ts], float)
    P["qv"] = np.ones((T, len(ASSETS)))
    W, reb = E.s_trend(P, ~np.isnan(P["close"]), list(ASSETS), SMA_N, 1)
    if caps: W = E.desk_caps(W)
    t0 = start_bar + D
    if t0 > ts[-1]: return []
    sim = E.run_sim(P, W, reb, t0, int(ts[-1]) + D)
    return list(zip([day(int(t)) for t in ts[sim["i0"]:sim["i1"]]], sim["eq"]))


def stop_flags(st, eq_rows, candles, expected_bar, now_ms=None, info=None):
    """Critérios de morte → flags de pausa automática (por livro, ou global para dados/API). bh_btc: só `info` (não pausa).
    Também grava st["kill_metrics"][livro] = cada critério com valor vs limite (lido por `python -m desk.health`)."""
    flags = {}
    info = {} if info is None else info
    hp = HL.params(); km = st.setdefault("kill_metrics", {})
    ref = st["last_revx_bar"] if st["last_revx_bar"] is not None else st["start_bar"]
    gap = None if ref is None else (expected_bar - ref) // D
    if ref is None or gap >= DATA_GAP_DAYS:
        flags["_global"] = f"DATA_GAP_REVX>={DATA_GAP_DAYS}d"
    api = HL.api_eval(st.get("health") or {}, now_ms or expected_bar + D, hp)
    if api["tripped"]: flags.setdefault("_global", f"{api['why']} ({api['value']})")
    for k, b in st["books"].items():
        since = b.get("since_bar"); sday = day(since) if since else None
        e = [float(r[k]) for r in eq_rows if r.get(k) and (sday is None or r["bar"] > sday)]
        m = {"forward_dd": HL.dd_eval(b["equity"], b["peak"], DD_PAUSE[k], informational=k in INFO_ONLY)}
        m["sharpe_12m"] = HL.sharpe_eval(e, {**hp, "kill_sharpe_days": SHARPE_WIN})
        m["divergence"] = {"value": "n/a (baseline)" if k in INFO_ONLY else f"INSUFFICIENT_DATA ({max(0, len(e) - 1)}/{DIVERGE_WIN} d)",
                           "limit": f"> {DIVERGE_MAX * 100:.0f} pp over {DIVERGE_WIN} d (paper vs backtest replica, same candles)",
                           "tripped": False, "measurable": False}
        m["data_gap_revx"] = {"value": f"{gap} d since last Revolut X daily bar" if gap is not None else "no Revolut X bar yet",
                              "limit": f">= {DATA_GAP_DAYS} d", "tripped": "_global" in flags and flags["_global"].startswith("DATA_GAP")}
        tgt = flags if k not in INFO_ONLY else info
        if m["forward_dd"]["tripped"]: tgt[k] = f"FORWARD_DD>{DD_PAUSE[k]:.0%}"
        if m["sharpe_12m"]["tripped"]: tgt.setdefault(k, "SHARPE_12M<0")
        if k not in INFO_ONLY and len(e) > DIVERGE_WIN and (since or st["start_bar"]) is not None:
            rep = dict(replica_equity(candles, since or st["start_bar"], caps=(k == "c3")))
            dd = [r for r in eq_rows if r.get(k) and (sday is None or r["bar"] > sday)][-(DIVERGE_WIN + 1):]
            if dd[0]["bar"] in rep and dd[-1]["bar"] in rep:
                pr = float(dd[-1][k]) / float(dd[0][k]) - 1; bt = rep[dd[-1]["bar"]] / rep[dd[0]["bar"]] - 1
                m["divergence"].update(value=f"{(pr - bt) * 100:+.2f} pp (paper {pr:+.2%} vs replica {bt:+.2%})",
                                       tripped=abs(pr - bt) > DIVERGE_MAX, measurable=True)
                if abs(pr - bt) > DIVERGE_MAX: flags.setdefault(k, f"PAPER_VS_BACKTEST_DIVERGENCE {pr - bt:+.1%}/30d")
        km[k] = m
    return flags


def ceiling_events(st, now_ms):
    """Teto (target_balance, 1000 USD): livro com equity ≥ teto → pausa trancada (bh_btc: só aviso). Devolve [(livro, equity)]."""
    ceil, out = HL.ceiling(env={}), []
    if ceil <= 0: return out
    for k, b in st["books"].items():
        if b["equity"] >= ceil and not b.get("ceiling"):
            b["ceiling"] = {"at": iso(now_ms), "equity": b["equity"], "ceiling": ceil}
            if k not in INFO_ONLY: b["paused"] = {"reason": f"CEILING>={ceil:g}", "at": iso(now_ms)}
            out.append((k, b["equity"]))
    return out

def br(x, d=2):
    return f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_trade(t):
    v = {"BUY": "COMPRA", "SELL": "VENDA"}[t["side"]]
    return f"• {BOOKS[t['book']]}: {v} {br(float(t['qty']), 6)} {t['coin']} a ${br(float(t['price']))} (${br(float(t['notional_usd']))}; {t['reason']})"


def run_once(now_ms=None, get=http_get, emit=True):
    _assert_paper_only()
    now_ms = now_ms or store.now_ms(); st = load_state(); st["runs"] += 1; st["last_run"] = iso(now_ms)
    m = fetch_market(now_ms, get)
    st["health"] = HL.record_run(st.get("health") or {}, now_ms, bool(m and m["source"] == "revx"),
                                 None if m and m["source"] == "revx" else ("fallback coinbase" if m else "sem velas"))
    if m is None:
        st["last_error"] = f"{iso(now_ms)} sem velas (Revolut X e Coinbase)"
        hp = HL.params(); h = st["health"]
        c = {"data_stale": HL.stale_eval(h.get("last_data_ok_ts"), h.get("first_ts"), now_ms, hp), "api_errors": HL.api_eval(h, now_ms, hp)}
        why = "; ".join(f"{k}: {v['value']}" for k, v in c.items() if v["tripped"])
        alerts = []
        if why and not st.get("paused"):
            st["paused"] = {"reason": why, "at": iso(now_ms)}
            st.setdefault("last_mark", {"source": "none"})
            alerts.append(_alert(st, f"SHADOW_C3:{day(now_ms)}:PAUSE:_global", "SHADOW_C3_PAUSE", [], [], ("_global", why)))
            if emit:
                for a in alerts: store.emit(a)
        save_state(st)
        return {"status": "NO_DATA", "flags": {"_global": why} if why else {}, "alerts": [a["id"] for a in alerts], "state": st}
    cs = m["candles"]; last_bar = min(cs[s][-1]["start"] for s in ASSETS)
    if m["source"] == "revx": st["last_revx_bar"] = last_bar
    expected_bar = (now_ms // D) * D - D
    mid = {s: (m["books"][s]["bid"] + m["books"][s]["ask"]) / 2 for s in ASSETS}
    for b in st["books"].values(): b["mark"] = _equity(b, mid)
    st["last_mark"] = {"ts": iso(now_ms), "mid": mid, "source": m["source"], "px_src": {s: m["books"][s]["src"] for s in ASSETS}}
    if st["last_bar"] is not None and last_bar <= st["last_bar"]:          # idempotente: vela já processada
        stop_flags(st, _read("equity.csv"), cs, expected_bar, now_ms, info={})   # só actualiza kill_metrics (acção só em vela nova)
        save_state(st); return {"status": "ALREADY_PROCESSED", "bar": day(last_bar), "state": st}

    bar = day(last_bar); ctx = {"ts": iso(now_ms), "bar": bar, "source": m["source"]}
    first = st["start_bar"] is None
    if first: st["start_bar"] = last_bar; st["created_at"] = iso(now_ms)
    new_bars = {s: [r for r in cs[s] if st["last_bar"] is None or r["start"] > st["last_bar"]] for s in ASSETS}
    closes = {s: [r["close"] for r in cs[s] if r["start"] <= last_bar] for s in ASSETS}
    trades, events = [], []
    sig = {"c3": target_weights(closes, caps=True), "c3_raw": target_weights(closes, caps=False)}
    gpause = st.get("paused")
    for k, b in st["books"].items():
        bctx = {**ctx, "book": k}
        if k == "bh_btc":
            if first or b.pop("needs_buy", False):
                q = b["cash"] / (m["books"]["BTC"]["ask"] * (1 + TAKER))
                t = _buy(b, "BTC", q, m["books"]["BTC"]["ask"], {**bctx, "w_target": "1.0", "w_before": "0", "px_src": m["books"]["BTC"]["src"]}, "BASELINE_BUY")
                trades.append(t)
            continue
        if gpause or b.get("paused"): continue
        trades += check_stops(b, new_bars, bctx) if not first else []
        trades += rebalance(b, sig[k], m["books"], bctx)
    px_close = {s: closes[s][-1] for s in ASSETS}
    for b in st["books"].values():   # equity diária = marcação ao MID ao vivo logo após o fecho (pós-trades), não ao fecho da vela
        b["equity"] = b["mark"] = _equity(b, mid); b["peak"] = max(b["peak"], b["equity"])
    st["last_bar"] = last_bar; st["last_signal"] = {k: {s: {kk: v for kk, v in d.items()} for s, d in w.items()} for k, w in sig.items()}
    eqr = {"bar": bar, "ts": iso(now_ms), "source": m["source"], "btc_close": px_close["BTC"], "eth_close": px_close["ETH"],
           **{k: f"{b['equity']:.4f}" for k, b in st["books"].items()},
           **{f"{k}_dd" if k != "bh_btc" else "bh_dd": f"{1 - b['equity'] / b['peak']:.4f}" for k, b in st["books"].items()},
           **{f"{k}_expo": f"{1 - b['cash'] / b['equity']:.4f}" for k, b in st["books"].items() if k != "bh_btc"}}
    rows = _read("equity.csv")
    info = {}
    flags = stop_flags(st, rows + [eqr], cs, expected_bar, now_ms, info=info)
    ceil_ev = ceiling_events(st, now_ms)
    for k, why in info.items():
        if why not in (st["books"][k].get("info_flags") or []):
            st["books"][k].setdefault("info_flags", []).append(why); events.append((k, "INFO:" + why))
    if "_global" in flags and not st.get("paused"):
        st["paused"] = {"reason": flags["_global"], "at": iso(now_ms)}; events.append(("_global", flags["_global"]))
    for k, why in flags.items():
        if k != "_global" and not st["books"][k].get("paused"):
            st["books"][k]["paused"] = {"reason": why, "at": iso(now_ms)}; events.append((k, why))
    eqr["paused"] = ";".join(f"{k}:{v}" for k, v in flags.items())
    _append("equity.csv", EQ_COLS, [eqr]); _append("trades.csv", TRADE_COLS, [t for t in trades if t])
    save_state(st)
    alerts = []
    c3_trades = [t for t in trades if t and t["book"] != "bh_btc"]
    if c3_trades: alerts.append(_alert(st, f"SHADOW_C3:{bar}:TRADE", "SHADOW_C3_TRADE", c3_trades, trades, None))
    for k, why in events:
        info_ev = why.startswith("INFO:")
        alerts.append(_alert(st, f"SHADOW_C3:{bar}:{'INFO' if info_ev else 'PAUSE'}:{k}:{why}", "SHADOW_C3_INFO" if info_ev else "SHADOW_C3_PAUSE",
                             [], trades, (k, why)))
    for k, eqv in ceil_ev:
        alerts.append(_alert(st, f"SHADOW_C3:{bar}:CEILING:{k}", "SHADOW_C3_CEILING", [], trades, (k, "CEILING"), ceiling=eqv))
    if emit:
        for a in alerts: store.emit(a)
    return {"status": "PROCESSED", "bar": bar, "source": m["source"], "trades": [t for t in trades if t], "flags": flags,
            "alerts": [a["id"] for a in alerts], "state": st}


def _alert(st, aid, typ, c3_trades, trades, pause, ceiling=None):
    eq = {k: st["books"][k]["equity"] for k in BOOKS}
    head = "🧪 SIMULADO · C3 NÃO VALIDADA (observação em paper, dinheiro fictício, nenhuma ordem real)"
    if ceiling is not None:
        k = pause[0]
        body = f"🎯 {BOOKS[k]}: " + HL.ceiling_text(ceiling, HL.ceiling(env={}), HL.reset_balance(), paper=True) + \
               (f" Comando: python -m desk.shadow.c3 rebase {k} --confirm" if k not in INFO_ONLY else " (baseline: só aviso, continua a correr)")
    elif pause and pause[1].startswith("INFO:"):
        k, why = pause
        body = f"ℹ️ {BOOKS[k]} (baseline de comparação): critério {why[5:]} — só aviso, continua a correr."
    elif pause:
        k, why = pause; who = "todos os livros" if k == "_global" else BOOKS[k]
        body = f"⏸️ Pausa automática ({who}): {why}. O bot-sombra parou de negociar até revisão."
    else:
        body = "\n".join(_fmt_trade(t) for t in c3_trades)
    tail = (f"Equity simulada: C3 ${br(eq['c3'])} · C3 sinal puro ${br(eq['c3_raw'])} · B&H BTC ${br(eq['bh_btc'])} (início $65 cada)."
            f"\nFonte de velas: {(st.get('last_mark') or {}).get('source', 'none')}. Notificação apenas (sem TAKEN/SKIPPED).")
    return {"id": aid, "type": typ, "mode": "shadow_c3_unvalidated", "tag": TAG, "autonomous": True, "reply_options": [],
            "coin": None, "text": f"{head}\n{body}\n{tail}", "data": {"equity": eq, "pause": pause, "n_trades": len(c3_trades)}}


def status():
    st = load_state(); rows = _read("equity.csv")
    out = {"tag": TAG, "label": LABEL, "variant": VARIANT_ID, "start_bar": day(st["start_bar"]) if st["start_bar"] else None,
           "last_bar": day(st["last_bar"]) if st["last_bar"] else None, "last_run": st["last_run"], "paused": st.get("paused"),
           "last_mark": st.get("last_mark"), "books": {}}
    for k, b in st["books"].items():
        out["books"][k] = {"name": BOOKS[k], "equity_close": round(b["equity"], 4), "equity_mark": round(b.get("mark", b["equity"]), 4),
                           "cash": round(b["cash"], 4), "units": b["units"], "avg": b["avg"], "dd": round(1 - b["equity"] / b["peak"], 4),
                           "blocked": b["blocked"], "paused": b.get("paused"), "ceiling": b.get("ceiling"),
                           "since_bar": day(b["since_bar"]) if b.get("since_bar") else None, "info_flags": b.get("info_flags")}
    out["ceiling"] = HL.ceiling(env={}); out["reset_balance"] = HL.reset_balance(); out["health"] = st.get("health", {}).get("fail_streak")
    out["signal"] = st.get("last_signal"); out["equity_rows"] = len(rows); out["trades"] = len(_read("trades.csv"))
    return out


def resume(book=None):
    """Retoma manualmente um livro (ou a pausa global) — só por decisão humana após revisão."""
    st = load_state()
    if book in (None, "_global"): st["paused"] = None
    if book: st["books"].get(book, {}).pop("paused", None)
    save_state(st)


def rebase(book):
    """Rebase manual (após o teto ou revisão): o livro volta a reset_balance (65 USD ≈ £50) em cash; pico/pausa/teto limpos.
    Métricas (DD, Sharpe, divergência) passam a contar só daqui para a frente. bh_btc recompra BTC na próxima vela."""
    st = load_state(); reset = HL.reset_balance(); books = list(BOOKS) if book == "all" else [book]
    if any(k not in BOOKS for k in books): raise SystemExit(f"livro desconhecido: {book}")
    for k in books:
        nb = new_book(reset); nb["since_bar"] = st.get("last_bar")
        if k == "bh_btc": nb["needs_buy"] = True
        nb["rebased_from"] = {"equity": st["books"][k]["equity"], "at": iso(store.now_ms())}
        st["books"][k] = nb
    save_state(st); return {"rebased": books, "reset_balance": reset}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "run-once":
        r = run_once(); r.pop("state", None); print(json.dumps(r, ensure_ascii=False, default=float, indent=1))
    elif cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, default=float, indent=1))
    elif cmd == "rebase":
        if len(argv) < 2 or "--confirm" not in argv: raise SystemExit("uso: python -m desk.shadow.c3 rebase <c3|c3_raw|bh_btc|all> --confirm")
        print(json.dumps(rebase(argv[1]), ensure_ascii=False))
    elif cmd == "resume":
        resume(argv[1] if len(argv) > 1 else None); print("ok")
    else:
        raise SystemExit("uso: python -m desk.shadow.c3 run-once | status | resume [c3|c3_raw|_global] | rebase <livro|all> --confirm")


if __name__ == "__main__":
    main()
