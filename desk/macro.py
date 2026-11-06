"""CONTEXTO MACRO (ideias OpenBB Apache-2.0 / dados yfinance Apache-2.0) — opcional, VETO-ONLY, shadow por defeito.

Séries diárias gratuitas e sem chave: S&P 500, VIX, índice do dólar (DXY) e yield 10 anos EUA (em pontos percentuais).
Fornecedores:
- `yfinance` (defeito): ^GSPC, ^VIX, DX-Y.NYB, ^TNX (+ BTC-USD diário longo, só para o estudo).
- `openbb` (OpenBB ODP 5.x, providers sem chave): cboe SPX/VIX, federal_reserve treasury_rates (10y). DXY não existe
  sem chave no OpenBB -> vem do yfinance se disponível, senão a série fica em falta (INSUFFICIENT_DATA para ela).
Nenhum dos dois é dependência obrigatória (requirements-optional.txt). Sem pacote/rede/cache -> INSUFFICIENT_DATA.

Regras (DESK_RULES.md, pré-registadas): uma vela diária com data D só é usável a partir de D+1 00:00 UTC + macro_lag_hours.
Flags: EQ_DOWN (SPX < SMA50), VOL_STRESS (VIX > macro_vix_high), USD_UP (DXY 20 velas > +macro_usd_up),
RATES_UP (10y 20 velas > +macro_rates_up pontos). flags ≥ macro_veto_flags -> RISK_OFF/VETO; 1 -> CAUTION; 0 -> OK.
O macro nunca aumenta tamanho, nunca abre, nunca mexe em stops/TP/saídas.

CLI:
  python -m desk.macro fetch [--provider yfinance|openbb] [--start 2014-01-01] [--out data_ext/macro]
  python -m desk.macro status            # estado macro agora (a partir da cache)
  python -m desk.macro compare A B       # qualidade: compara duas caches (ex. yfinance vs openbb)
"""
from __future__ import annotations
import argparse, bisect, json, os, time
from datetime import datetime, timezone, timedelta

D_MS = 86_400_000
H_MS = 3_600_000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "data_ext", "macro")
SERIES = ("spx", "vix", "dxy", "us10y")
YF = {"spx": "^GSPC", "vix": "^VIX", "dxy": "DX-Y.NYB", "us10y": "^TNX", "btc_daily": "BTC-USD"}
OK, CAUTION, RISK_OFF, ABST = "OK", "CAUTION", "RISK_OFF", "INSUFFICIENT_DATA"


def _g(rules, k, d):
    try: return rules.p.get(k, d)
    except AttributeError: return d


def mode(rules): return _g(rules, "macro_mode", "shadow")


def _day_ms(date_str):
    return int(datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


# ---------------- cache ----------------
def save(key, bars, provider, symbol, out=DEFAULT_DIR):
    os.makedirs(out, exist_ok=True)
    bars = sorted({b["date"]: b for b in bars if b.get("close") is not None}.values(), key=lambda b: b["date"])
    doc = {"key": key, "symbol": symbol, "provider": provider, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "bars": bars}
    p = os.path.join(out, f"{key}.json"); tmp = p + ".tmp"
    json.dump(doc, open(tmp, "w")); os.replace(tmp, p)
    return p


def load(data_dir=DEFAULT_DIR, keys=SERIES):
    """{key: {"avail": [ms], "close": [float], "date": [str], "provider": str}} só para séries existentes."""
    ctx = {}
    for k in keys:
        p = os.path.join(data_dir, f"{k}.json")
        if not os.path.exists(p): continue
        try: doc = json.load(open(p))
        except Exception: continue
        bars = [b for b in doc.get("bars", []) if isinstance(b.get("close"), (int, float))]
        if not bars: continue
        ctx[k] = {"date": [b["date"] for b in bars], "close": [float(b["close"]) for b in bars],
                  "day": [_day_ms(b["date"]) for b in bars], "provider": doc.get("provider")}
    return ctx


# ---------------- avaliação point-in-time ----------------
def _usable(series, now, lag_h):
    """Índice (exclusivo) das velas usáveis em `now`: data D usável a partir de D + 1 dia + lag."""
    cutoff = now - D_MS - lag_h * H_MS
    return bisect.bisect_right(series["day"], cutoff)


def evaluate(ctx, now, rules):
    """Estado macro em `now` (ms). Nunca olha para velas ainda não publicadas."""
    lag = float(_g(rules, "macro_lag_hours", 1)); stale = float(_g(rules, "macro_max_stale_days", 4)) * D_MS
    out, flags = {}, []

    def window(k, need):
        s = (ctx or {}).get(k)
        if not s: return None, {"status": ABST, "why": "sem cache"}
        j = _usable(s, now, lag)
        if j < need: return None, {"status": ABST, "why": f"histórico curto ({j}<{need})"}
        if now - (s["day"][j - 1] + D_MS) > stale:
            return None, {"status": ABST, "why": f"desatualizado (última {s['date'][j - 1]})"}
        return s["close"][j - need:j], {"status": "ok", "asof": s["date"][j - 1]}

    c, info = window("spx", 50)
    if c:
        sma = sum(c) / 50; f = c[-1] < sma; info.update(value=round(c[-1], 2), sma50=round(sma, 2), flag=f)
        if f: flags.append("EQ_DOWN")
    out["spx"] = info
    c, info = window("vix", 1)
    if c:
        th = float(_g(rules, "macro_vix_high", 25)); f = c[-1] > th; info.update(value=round(c[-1], 2), flag=f)
        if f: flags.append("VOL_STRESS")
    out["vix"] = info
    c, info = window("dxy", 21)
    if c:
        r = c[-1] / c[0] - 1; f = r > float(_g(rules, "macro_usd_up", 0.02)); info.update(value=round(c[-1], 3), ret20=round(r, 4), flag=f)
        if f: flags.append("USD_UP")
    out["dxy"] = info
    c, info = window("us10y", 21)
    if c:
        dlt = c[-1] - c[0]; f = dlt > float(_g(rules, "macro_rates_up", 0.30)); info.update(value=round(c[-1], 3), chg20=round(dlt, 3), flag=f)
        if f: flags.append("RATES_UP")
    out["us10y"] = info
    n_ok = sum(1 for v in out.values() if v["status"] == "ok")
    if n_ok < int(_g(rules, "macro_min_series", 3)):
        status, action = ABST, "NO_OPINION"
    else:
        vf = int(_g(rules, "macro_veto_flags", 2))
        status = RISK_OFF if len(flags) >= vf else CAUTION if flags else OK
        action = "VETO" if status == RISK_OFF else "KEEP"
    return {"status": status, "action": action, "flags": flags, "n_series": n_ok, "series": out, "mode": mode(rules),
            "size_mult": 0.0 if action == "VETO" else 1.0}


def summary(m) -> str:
    if not m: return ""
    vals = []
    for k, v in m["series"].items():
        vals.append(f"{k} {v['value']}" if v.get("status") == "ok" else f"{k} ?")
    return (f"Macro ({m['mode']}): {m['status']} → {m['action']}" + (f" [{', '.join(m['flags'])}]" if m["flags"] else "")
            + " | " + " · ".join(vals))


_LIVE = {"t": 0, "ctx": None}


def live_decision(rules, now=None, data_dir=DEFAULT_DIR, refresh=True, log=print):
    """Para o risk_officer: lê a cache; se estiver velha e o yfinance existir, tenta refrescar (no máx. 1×/6h por processo).
    Qualquer falha -> INSUFFICIENT_DATA (sem efeito)."""
    now = now or int(time.time() * 1000)
    try:
        ctx = load(data_dir)
        m = evaluate(ctx, now, rules)
        if refresh and m["status"] == ABST and time.time() - _LIVE["t"] > 6 * 3600:
            _LIVE["t"] = time.time()
            try:
                start = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%d")
                fetch(str(_g(rules, "macro_provider", "yfinance")), start, data_dir, merge=True, keys=SERIES)
                m = evaluate(load(data_dir), now, rules)
            except Exception as e:
                log(f"macro: refresh indisponível ({type(e).__name__}) -> INSUFFICIENT_DATA")
        return m
    except Exception as e:
        log(f"macro: erro ({type(e).__name__}) -> sem efeito"); return None


# ---------------- fornecedores (opcionais) ----------------
def _df_bars(df, col="close", scale=1.0):
    bars = []
    for idx, row in df.iterrows():
        v = row[col] if col in row else row[col.capitalize()]
        try: v = float(v)
        except (TypeError, ValueError): continue
        if v != v: continue   # NaN
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        bars.append({"date": d, "close": v * scale})
    return bars


def fetch_yfinance(key, start):
    import yfinance as yf   # opcional
    df = yf.Ticker(YF[key]).history(start=start, interval="1d", auto_adjust=False, actions=False, timeout=10)
    if df is None or df.empty: return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [b for b in _df_bars(df, "Close") if b["date"] < today]   # só sessões completas


def fetch_openbb(key, start):
    from openbb import obb   # opcional (OpenBB ODP 5.x)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if key in ("spx", "vix"):
        df = obb.cboe.index.historical({"spx": "SPX", "vix": "VIX"}[key], start_date=start).to_dataframe()
        bars = _df_bars(df, "close")
    elif key == "us10y":
        df = obb.federal_reserve.treasury_rates(start_date=start).to_dataframe()
        bars = _df_bars(df, "year_10", 100.0)   # fracção -> pontos percentuais (como ^TNX)
    else:
        raise KeyError(f"{key} sem fornecedor OpenBB sem chave")
    return [b for b in bars if b["date"] < today]


def fetch(provider, start, out=DEFAULT_DIR, merge=False, keys=SERIES, log=print):
    res = {}
    for k in keys:
        src = provider
        try:
            bars = fetch_openbb(k, start) if provider == "openbb" else fetch_yfinance(k, start)
        except KeyError:
            src = "yfinance"
            try: bars = fetch_yfinance(k, start)
            except Exception as e: log(f"macro: {k} indisponível ({type(e).__name__})"); continue
        if merge:
            old = os.path.join(out, f"{k}.json")
            if os.path.exists(old):
                try: bars = json.load(open(old))["bars"] + bars
                except Exception: pass
        if bars:
            res[k] = save(k, bars, src, YF.get(k), out); log(f"macro: {k} {len(bars)} velas ({src})")
    return res


# ---------------- estudos ----------------
def regime_days(ctx, rules, start_day, end_day):
    """[(day_ms, status)] avaliado às 00:00 UTC de cada dia (como um replay faria)."""
    out = []; t = start_day
    while t <= end_day:
        out.append((t, evaluate(ctx, t, rules)["status"])); t += D_MS
    return out


def btc_forward_study(ctx, btc_bars, rules, horizon=30, split=0.6):
    """Retorno BTC (fecho→fecho) nos `horizon` dias seguintes a cada dia, agrupado pelo estado macro desse dia.
    Avaliação às 00:00 UTC do dia D+1 da vela BTC D (fecho conhecido), entrada = fecho D."""
    days = [_day_ms(b["date"]) for b in btc_bars]; cl = [b["close"] for b in btc_bars]
    rows = []
    for i in range(len(cl) - horizon):
        st = evaluate(ctx, days[i] + D_MS, rules)["status"]
        rows.append((days[i], st, cl[i + horizon] / cl[i] - 1))
    if not rows: return {}
    cut = rows[0][0] + (rows[-1][0] - rows[0][0]) * split
    def agg(rs):
        g = {}
        for _, s, r in rs: g.setdefault(s, []).append(r)
        return {s: {"n": len(v), "mean": sum(v) / len(v), "hit": sum(1 for x in v if x > 0) / len(v)} for s, v in sorted(g.items())}
    return {"horizon_days": horizon, "first": rows[0][0], "last": rows[-1][0], "cut": cut,
            "in_sample": agg([r for r in rows if r[0] < cut]), "oos": agg([r for r in rows if r[0] >= cut]), "full": agg(rows)}


def compare(dir_a, dir_b, keys=SERIES):
    a, b = load(dir_a, keys), load(dir_b, keys); out = {}
    for k in keys:
        if k not in a or k not in b: out[k] = None; continue
        ma = dict(zip(a[k]["date"], a[k]["close"])); mb = dict(zip(b[k]["date"], b[k]["close"]))
        common = sorted(set(ma) & set(mb))
        devs = sorted(abs(ma[d] / mb[d] - 1) for d in common if mb[d])
        out[k] = {"common_days": len(common), "only_a": len(set(ma) - set(mb)), "only_b": len(set(mb) - set(ma)),
                  "median_dev": devs[len(devs) // 2] if devs else None, "max_dev": devs[-1] if devs else None}
    return out


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--provider", default="yfinance", choices=["yfinance", "openbb"])
    f.add_argument("--start", default="2014-01-01"); f.add_argument("--out", default=DEFAULT_DIR)
    f.add_argument("--with-btc", action="store_true", help="também BTC-USD diário (yfinance) para o estudo")
    s = sub.add_parser("status"); s.add_argument("--data-dir", default=DEFAULT_DIR)
    c = sub.add_parser("compare"); c.add_argument("a"); c.add_argument("b")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.provider, a.start, a.out)
        if a.with_btc: save("btc_daily", fetch_yfinance("btc_daily", a.start), "yfinance", YF["btc_daily"], a.out)
    elif a.cmd == "status":
        from .rules import load_rules
        m = evaluate(load(a.data_dir), int(time.time() * 1000), load_rules()); print(summary(m)); print(json.dumps(m, indent=2))
    else:
        print(json.dumps(compare(a.a, a.b), indent=2))


if __name__ == "__main__":
    main()
