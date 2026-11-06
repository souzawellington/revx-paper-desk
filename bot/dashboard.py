"""Dashboard local SOMENTE-LEITURA.  python -m bot.dashboard [--port 8050] [--host 127.0.0.1]

- Zero dependências extra (http.server da stdlib). Front-end: JS simples + TradingView Lightweight Charts v5.2.1
  (Apache-2.0) VENDORIZADO em dashboard_static/vendor (sem CDN em runtime; atribuição no rodapé, ver NOTICE).
- Conta: se REVX_API_KEY e REVX_PRIVATE_KEY_PATH (ou ~/.revx-keys/private.pem) existirem -> Revolut X
  (apenas GET /balances e GET /orders/active, via ReadOnlyClient que recusa qualquer método != GET);
  caso contrário -> estado paper reconstruído de logs/audit.jsonl.
- Preços/candles: endpoints públicos Revolut X (cache para respeitar 1 req/s).
- NUNCA coloca, altera ou cancela ordens.
"""
from __future__ import annotations
import argparse, base64, hmac, json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from .config import load_config
from .revolutx.client import RevolutXClient, load_private_key

STATIC = os.path.join(os.path.dirname(__file__), "dashboard_static")


class ReadOnlyClient:
    """Wrapper que só permite GET. Qualquer escrita levanta PermissionError (defesa em profundidade)."""
    ALLOWED = {"balances", "active_orders", "public_tickers", "public_candles", "public_pairs"}

    def __init__(self, client: RevolutXClient):
        self._c = client
        orig = client._request

        def guarded(method, *a, **k):
            if method.upper() != "GET":
                raise PermissionError(f"dashboard é só-leitura: {method} bloqueado")
            return orig(method, *a, **k)
        client._request = guarded

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise PermissionError(f"dashboard é só-leitura: {name} não permitido")
        return getattr(self._c, name)


def read_audit(log_dir: str, limit: int = 5000) -> list[dict]:
    path = os.path.join(log_dir, "audit.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = f.readlines()[-limit:]
    out = []
    for ln in lines:
        try: out.append(json.loads(ln))
        except Exception: pass
    return out


def paper_state(events: list[dict]) -> dict:
    """Reconstrói posições paper a partir dos fills auditados."""
    pos, orders = {}, []
    for e in events:
        if e.get("event") != "order": continue
        o, r = e.get("order", {}), e.get("result", {})
        orders.append({"ts": e["ts"], "symbol": o.get("ticker"), "side": o.get("side"), "qty": o.get("qty"),
                       "price": r.get("price"), "status": r.get("status"), "reason": o.get("reason"), "stop": o.get("stop_price")})
        if r.get("status") not in ("FILLED", "SUBMITTED", "STAGED"): continue
        t, q, px = o["ticker"], float(o["qty"]), float(r.get("price") or 0)
        if o["side"] == "BUY":
            p = pos.setdefault(t, {"qty": 0.0, "entry": 0.0, "stop": None})
            p["entry"] = (p["entry"] * p["qty"] + px * q) / (p["qty"] + q) if p["qty"] + q else px
            p["qty"] += q; p["stop"] = o.get("stop_price") or p["stop"]
        else:
            p = pos.get(t)
            if p:
                p["qty"] -= q
                if p["qty"] <= 1e-12: pos.pop(t)
    return {"positions": pos, "orders": orders}


class State:
    def __init__(self, cfg):
        self.cfg, self.lock = cfg, threading.Lock()
        self.pub = ReadOnlyClient(RevolutXClient())
        self.auth, self.auth_error = None, None
        key = os.environ.get("REVX_API_KEY")
        pem = os.environ.get("REVX_PRIVATE_KEY_PATH") or os.path.expanduser("~/.revx-keys/private.pem")
        if key and os.path.exists(pem):
            try:
                self.auth = ReadOnlyClient(RevolutXClient(key, load_private_key(open(pem, "rb").read())))
            except Exception as e:
                self.auth_error = f"chave inválida: {type(e).__name__}"
        self.cache = {}
        from .live_view import Prices, Marks
        self.live_prices = Prices(self.pub, cfg.region, ttl=20.0)
        self.marks = Marks(os.path.join(cfg.log_dir, "dashboard_marks.jsonl"), every=300)

    def live(self):
        from .live_view import live_snapshot
        return live_snapshot(self.live_prices, self.marks)

    def cached(self, key, ttl, fn):
        with self.lock:
            hit = self.cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        try:
            val = fn()
        except Exception as e:
            val = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        with self.lock:
            self.cache[key] = (time.time(), val)
        return val

    def prices(self):
        def f():
            out = {}
            for t in self.pub.public_tickers(list(self.cfg.symbols), self.cfg.region):
                out.setdefault(t["symbol"].replace("/", "-"), {k: float(t[k]) for k in ("bid", "ask", "mid", "last_price") if t.get(k)})
            return out
        return self.cached("prices", 5, f)

    def candles(self, sym, interval):
        def f():
            until = int(time.time() * 1000); since = until - interval * 60_000 * 100
            return self.pub.public_candles(sym, interval, since, until, self.cfg.region)
        return self.cached(("candles", sym, interval), 60, f)

    def account(self, events):
        if self.auth:
            def f():
                bals = self.auth.balances()
                act = self.auth.active_orders()
                return {"balances": bals, "active_orders": act}
            acc = self.cached("account", 10, f)
            px = self.prices()
            if "error" not in acc and "error" not in px:
                q = self.cfg.quote_currency; eq = 0.0
                for b in acc["balances"]:
                    tot = float(b["total"])
                    if b["currency"] == q: eq += tot
                    else:
                        m = px.get(f"{b['currency']}-{q}", {}).get("mid")
                        b["value_quote"] = tot * m if m else None
                        eq += b["value_quote"] or 0
                acc["equity_quote"] = eq
            st = {}
            sp = os.path.join(self.cfg.log_dir, "revx_positions.json")
            if os.path.exists(sp):
                st = json.load(open(sp))
            return {"source": "revolutx (read-only)", **acc, "bot_positions": st}
        ps = paper_state(events)
        return {"source": "paper (logs/audit.jsonl)", "positions": ps["positions"], "auth_error": self.auth_error}

    def snapshot(self):
        ev = read_audit(self.cfg.log_dir)
        eq = [e for e in ev if e.get("event") == "equity"]
        cyc = [e for e in ev if e.get("event") == "cycle"]
        last_eq = eq[-1] if eq else {}
        return {
            "now": time.time(), "symbols": list(self.cfg.symbols), "quote": self.cfg.quote_currency,
            "dry_run": self.cfg.dry_run, "broker": self.cfg.broker,
            "account": self.account(ev), "prices": self.prices(),
            "equity_series": [[e["ts"], e.get("equity"), e.get("dd")] for e in eq[-500:]],
            "risk": {"mode": last_eq.get("mode"), "dd": last_eq.get("dd"), "max_dd": last_eq.get("max_dd"),
                     "reduce_at": self.cfg.portfolio_dd_reduce, "suspend_at": self.cfg.portfolio_dd_suspend},
            "circuit": (cyc[-1].get("circuit") if cyc else None) or last_eq.get("circuit") or {"tripped": False, "reason": "", "errors": 0},
            "cycles": [{"ts": c["ts"], "decisions": c.get("decisions", [])} for c in cyc[-30:]][::-1],
            "orders": paper_state(ev)["orders"][-100:][::-1],
            "staged": self._staged(),
        }

    def _staged(self):
        p = os.path.join(self.cfg.log_dir, "staged_orders.jsonl")
        if not os.path.exists(p): return []
        return [json.loads(l) for l in open(p).readlines()[-50:]][::-1]

    def chart(self, sym, interval):
        ev = read_audit(self.cfg.log_dir)
        marks = [{"ts": e["ts"], "side": e["order"]["side"], "price": e["result"].get("price"), "reason": e["order"].get("reason"),
                  "stop": e["order"].get("stop_price")}
                 for e in ev if e.get("event") == "order" and e.get("order", {}).get("ticker") == sym]
        return {"symbol": sym, "candles": self.candles(sym, interval), "markers": marks}


def desk_snapshot() -> dict:
    """Estado do desk (CSVs em desk/state) — apenas leitura."""
    try:
        from desk import store as ds
        from desk.auditor import stats
        from desk.rules import load_rules
    except Exception as e:
        return {"error": f"desk indisponível: {e}"}
    rules = load_rules()
    ob = ds.outbox()
    for a in ob:
        if a.get("chart_png"): a["chart_url"] = "/desk/chart/" + os.path.basename(a["chart_png"])
    replay = None
    rp = os.path.join(ds.STATE, "replay", "replay_results.json")
    if os.path.exists(rp):
        replay = json.load(open(rp)).get("score")
    return {"watchlist": ds.read("watchlist.csv"), "zones": [z for z in ds.read("zones.csv") if z["status"] not in ("DROPPED",)][-200:],
            "plans": ds.read("trade_plan.csv")[-50:][::-1], "decisions": ds.read("decisions.csv")[-50:][::-1],
            "positions": [p for p in ds.read("positions.csv") if p.get("status") == "OPEN"],
            "journal": ds.read("journal.csv")[-60:][::-1], "outbox": ob[-50:][::-1], "stats": stats(rules),
            "thresholds": {k: rules.p[k] for k in rules.p if k.startswith("threshold_")}, "replay": replay}


import re as _re
_COIN_RE = _re.compile(r"^[A-Z0-9]{1,15}-[A-Z]{2,5}$")
VENDOR = {"lightweight-charts.standalone.production.js": "application/javascript",
          "NOTICE-lightweight-charts.txt": "text/plain; charset=utf-8", "LICENSE-lightweight-charts.txt": "text/plain; charset=utf-8"}


def _sec(ms):
    try: return int(float(ms)) // 1000
    except (TypeError, ValueError): return None


def desk_coins() -> list[str]:
    """Moedas com algo para desenhar: zonas activas, planos, posições, PRIME na watchlist e pares do replay."""
    try:
        from desk import store as ds
    except Exception:
        return []
    c = set()
    for z in ds.read("zones.csv"):
        if z.get("status") not in ("INVALID", "DROPPED"): c.add(z["coin"])
    for n in ("trade_plan.csv", "positions.csv"): c |= {r["coin"] for r in ds.read(n)}
    c |= {w["coin"] for w in ds.read("watchlist.csv") if w.get("tag") == "PRIME"}
    rp = os.path.join(ds.STATE, "replay", "replay_results.json")
    if os.path.exists(rp):
        try: c |= set(json.load(open(rp)).get("symbols", []))
        except Exception: pass
    return sorted(x for x in c if _COIN_RE.match(x or ""))


def _desk_candles(coin, tf):
    """Velas da cache do desk (desk/state/cache, sem rede); para pares do replay sem cache usa data/candles_*_60.json."""
    from desk import store as ds
    p = os.path.join(ds.STATE, "cache", f"{coin}_{tf}.json")
    if os.path.exists(p):
        return json.load(open(p)), "desk cache"
    h = os.path.join(os.path.dirname(ds.STATE), "..", "data", f"candles_{coin}_60.json")
    if os.path.exists(h):
        from bot.variants import resample
        return resample(json.load(open(h)), tf // 60), "replay cache (data/)"
    return [], "sem velas em cache"


def desk_chart(coin: str, tf: int = 240, bars: int = 400, replay: bool = True) -> dict:
    """Velas + zonas FVG + planos + posições (entrada/stop/TP/saída) + trades do replay. Só leitura de ficheiros."""
    from desk import store as ds
    raw, src = _desk_candles(coin, tf)
    cs = sorted(({"time": _sec(c["start"]), "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]),
                  "close": float(c["close"])} for c in raw if c.get("start") is not None), key=lambda x: x["time"])
    dedup = {}
    for c in cs: dedup[c["time"]] = c
    cs = list(dedup.values())[-bars:]
    t0 = cs[0]["time"] if cs else 0; t_end = cs[-1]["time"] if cs else 0
    zones = []
    for z in ds.read("zones.csv"):
        if z["coin"] != coin or z.get("status") in ("DROPPED",): continue
        ft = _sec(z.get("formed_ts"))
        if ft is None or (cs and ft < t0 - 30 * 86400): continue
        zones.append({"zone_id": z["zone_id"], "rank": z.get("rank"), "top": ds.f(z["zone_top"]), "bottom": ds.f(z["zone_bottom"]),
                      "status": z["status"], "from": max(ft, t0) if cs else ft, "to": t_end,
                      "tested": _sec(z.get("tested_ts")) if z.get("tested_ts") not in ("", "-1") else None,
                      "confirm": _sec(z.get("confirm_ts")) if z.get("confirm_ts") else None})
    trades = []
    for p in ds.read("positions.csv"):
        if p["coin"] != coin or p.get("status") == "VOID": continue
        trades.append({"source": "desk", "id": p["pid"], "status": p["status"], "entry": ds.f(p["entry"]),
                       "stop": ds.f(p["stop"]), "initial_stop": ds.f(p.get("initial_stop")), "tp": ds.f(p.get("tp_price")),
                       "open": _sec(p.get("opened_ts")), "close": _sec(p.get("exit_ts")) if p.get("exit_ts") else None,
                       "exit": ds.f(p.get("exit")), "rule": p.get("exit_rule") or ""})
    have = {t["id"] for t in trades}
    plans = [{"id": p["plan_id"], "entry": ds.f(p["entry"]), "stop": ds.f(p["stop"]), "tp": ds.f(p.get("tp_price")),
              "created": _sec(p.get("created_ts"))} for p in ds.read("trade_plan.csv") if p["coin"] == coin and p["plan_id"] not in have]
    rp = os.path.join(ds.STATE, "replay", "replay_results.json")
    if replay and os.path.exists(rp):
        try:
            for t in json.load(open(rp)).get("trades", []):
                if t["symbol"] != coin: continue
                o, c = _sec(t["entry_ts"]), _sec(t["exit_ts"])
                if cs and (c or 0) < t0: continue
                trades.append({"source": "replay", "id": t["pid"], "status": "CLOSED", "entry": t["entry"], "stop": t["stop"],
                               "initial_stop": t["stop"], "tp": t.get("tp"), "open": o, "close": c, "exit": t["exit"],
                               "rule": t["why"], "r": t.get("net_r")})
        except Exception:
            pass
    return {"coin": coin, "tf": tf, "source": src, "candles": cs, "zones": zones, "trades": trades, "plans": plans}


def desk_equity() -> dict:
    """Curva de equity paper (journal RESULT, modo PAPER) e do replay histórico (PnL acumulado por saída)."""
    from desk import store as ds
    from desk.rules import load_rules
    eq0 = float(load_rules().paper_equity)
    from datetime import datetime
    pts, eq = [], eq0
    rows = sorted((r for r in ds.read("journal.csv") if r.get("line") == "RESULT" and r.get("mode") == "PAPER"), key=lambda r: r["ts"])
    for r in rows:
        try: t = int(datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=__import__("datetime").timezone.utc).timestamp())
        except ValueError: continue
        eq += ds.f(r.get("amount_usd"), 0.0); pts.append([t, round(eq, 2)])
    rep = []
    rp = os.path.join(ds.STATE, "replay", "replay_results.json")
    if os.path.exists(rp):
        try:
            d = json.load(open(rp)); e = float(d.get("score", {}).get("equity0") or eq0)
            for t in sorted(d.get("trades", []), key=lambda x: x["exit_ts"]):
                e += float(t["pnl"]); rep.append([_sec(t["exit_ts"]), round(e, 2)])
        except Exception:
            rep = []
    def dedupe(xs):
        out = {}
        for t, v in xs: out[t] = v
        return [[t, out[t]] for t in sorted(out)]
    return {"equity0": eq0, "paper": dedupe(pts), "replay": dedupe(rep)}


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PW_FILE = os.path.join(ROOT, ".dashboard_password")


def load_auth(env=None) -> tuple[str, str] | None:
    """(utilizador, senha) para HTTP Basic Auth: env DASHBOARD_PASSWORD, ou ficheiro DASHBOARD_PASSWORD_FILE /
    .dashboard_password (chmod 600). Nunca hardcoded. None = sem auth (só aceitável em 127.0.0.1 sem túnel)."""
    env = os.environ if env is None else env
    user = env.get("DASHBOARD_USER") or "paper"
    pw = env.get("DASHBOARD_PASSWORD")
    if not pw:
        fp = env.get("DASHBOARD_PASSWORD_FILE") or DEFAULT_PW_FILE
        if os.path.exists(fp):
            with open(fp) as f: pw = f.read().strip()
    return (user, pw) if pw else None


# Rotas — TODAS GET e só-leitura. Não existe nenhuma rota que mude estado (sem rebase/unkill/resume/ordens).
GET_ROUTES = ("/", "/index.html", "/live", "/classic", "/app.js", "/live.js", "/api/live", "/api/state", "/api/chart",
              "/api/desk", "/api/desk/coins", "/api/desk/chart", "/api/desk/equity", "/healthz")


def make_handler(state: State, auth: tuple[str, str] | None = None):
    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode() if auth else None

    class H(BaseHTTPRequestHandler):
        server_version = "dashboard"; sys_version = ""
        def log_message(self, *a): pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY"); self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def _authed(self) -> bool:
            if not token: return True
            h = self.headers.get("Authorization") or ""
            return h.startswith("Basic ") and hmac.compare_digest(h[6:].strip().encode(), token.encode())

        def do_GET(self):
            u = urlparse(self.path); q = parse_qs(u.query)
            if u.path == "/healthz":
                return self._send(200, b"ok", "text/plain")
            if not self._authed():
                return self._send(401, b'{"error":"auth"}', extra={"WWW-Authenticate": 'Basic realm="Painel SIMULADO", charset="UTF-8"'})
            if u.path == "/api/live":
                return self._send(200, json.dumps(state.live(), default=str, ensure_ascii=False).encode())
            if u.path in ("/", "/live", "/live.html"):
                return self._send(200, open(os.path.join(STATIC, "live.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/live.js":
                return self._send(200, open(os.path.join(STATIC, "live.js"), "rb").read(), "application/javascript")
            if u.path == "/api/state":
                return self._send(200, json.dumps(state.snapshot(), default=str).encode())
            if u.path == "/api/chart":
                sym = q.get("symbol", [state.cfg.symbols[0]])[0]
                if sym not in state.cfg.symbols:
                    return self._send(400, b'{"error":"symbol"}')
                iv = int(q.get("interval", ["60"])[0])
                return self._send(200, json.dumps(state.chart(sym, iv), default=str).encode())
            if u.path == "/api/desk":
                return self._send(200, json.dumps(desk_snapshot(), default=str).encode())
            if u.path == "/api/desk/coins":
                return self._send(200, json.dumps(desk_coins()).encode())
            if u.path == "/api/desk/chart":
                coin = q.get("coin", [""])[0]
                if not _COIN_RE.match(coin) or coin not in desk_coins():
                    return self._send(400, b'{"error":"coin"}')
                tf = int(q.get("tf", ["240"])[0]) if q.get("tf", ["240"])[0] in ("60", "240", "1440") else 240
                return self._send(200, json.dumps(desk_chart(coin, tf), default=str).encode())
            if u.path == "/api/desk/equity":
                return self._send(200, json.dumps(desk_equity(), default=str).encode())
            if u.path.startswith("/vendor/"):
                name = os.path.basename(u.path)
                if name in VENDOR:
                    return self._send(200, open(os.path.join(STATIC, "vendor", name), "rb").read(), VENDOR[name])
                return self._send(404, b"{}")
            if u.path.startswith("/desk/chart/"):
                name = os.path.basename(u.path)
                from desk import store as dstore
                fp = os.path.join(dstore.STATE, "charts", name)
                if name.endswith(".png") and os.path.exists(fp):
                    return self._send(200, open(fp, "rb").read(), "image/png")
                return self._send(404, b"{}")
            if u.path in ("/classic", "/index.html"):
                return self._send(200, open(os.path.join(STATIC, "index.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/app.js":
                return self._send(200, open(os.path.join(STATIC, "app.js"), "rb").read(), "application/javascript")
            self._send(404, b"{}")

        def do_POST(self): self._send(405, b'{"error":"read-only"}')
        do_PUT = do_DELETE = do_PATCH = do_POST
    return H


def _sampler(st: State, every=300):
    """Marca a equity ao vivo dos 4 bots a cada 5 min (log próprio), mesmo sem ninguém a ver a página."""
    while True:
        try: st.live()
        except Exception: pass
        time.sleep(every)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8050); ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--require-auth", action="store_true", help="recusa arrancar sem senha (obrigatório com túnel público)")
    a = ap.parse_args()
    auth = load_auth()
    if a.require_auth and not auth:
        raise SystemExit("sem senha: define DASHBOARD_PASSWORD ou cria .dashboard_password (chmod 600)")
    st = State(load_config())
    threading.Thread(target=_sampler, args=(st,), daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(st, auth))
    print(f"Dashboard só-leitura em http://{a.host}:{a.port}  (conta: {'Revolut X' if st.auth else 'paper'}; "
          f"auth: {'basic (' + auth[0] + ')' if auth else 'NENHUMA'})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
