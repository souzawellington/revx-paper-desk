"""Estudo multi-variante ("vários bots") sobre as ENTRADAS do desk FVG: filtros de entrada × saídas.
Disciplina: split 60/40 por tempo; filtros derivados SÓ do in-sample; grelha pré-registada (ficheiro + SHA256)
ANTES de qualquer cálculo no holdout; selecção no IS; holdout avaliado uma vez; DSR + White RC para N variantes.

python -m desk.research.exitgrid features   # fase 1: replay + features + análise vencedores/perdedores (só IS)
python -m desk.research.exitgrid prereg     # fase 2: escreve desk/research/prereg_exitgrid.json (+ hash)
python -m desk.research.exitgrid run        # fase 3: grelha no IS, selecção, DSR/RC, holdout UMA vez

Nada aqui toca execution_mode, live/, chaves ou limiares do auditor. Só lê dados e escreve relatórios.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json, math, os, statistics
import numpy as np

try:
    from numba import njit
except Exception:                      # sem numba (venv do desk/testes): Python puro, mesmos resultados
    def njit(*a, **k):
        if a and callable(a[0]): return a[0]
        return lambda f: f

H, D = 3_600_000, 86_400_000
FIRST = 1697824800000                  # 2023-10-20 18:00 UTC (início Coinbase 1H)
SPLIT = 1754611200000                  # 2025-08-08 00:00 UTC ≈ 60% do intervalo
LAST = 1792432800000                   # fim dos dados (exclusivo)
TAKER, SLIP, HARD = 0.0009, 0.001, 0.08
RISK, CAP, MAXPOS, EQ0 = 0.01, 0.15, 5, 10_000.0
MAX_HOLD = 720                         # horas (30d) quando não há time-stop
STATE = "desk/state/exitgrid"
PREREG = "desk/research/prereg_exitgrid.json"

# ---------- grelha de saídas (fixa; não depende dos dados) ----------
STOPS = [("wick", 0.0), ("atr", 1.0), ("atr", 1.5), ("atr", 2.0), ("atr", 3.0), ("pct", 0.03), ("pct", 0.05), ("pct", 0.08)]
TPS = [1.0, 1.5, 2.0, 3.0, 0.0]        # 0 = sem TP
TRAILS = [("none", 0.0), ("chand", 3.0), ("chand", 2.0)]
BES = [0, 1]                           # 1 = stop → entrada após +1R
TIMES = [0, 48, 168]                   # 0 = sem time-stop (cap 720h)
REF_EXIT = {"stop": ("atr", 2.0), "tp": 2.0, "trail": ("none", 0.0), "be": 0, "time": 0}


def exit_grid():
    out = []
    for (sk, sv), tp, (tk, tv), be, ts in itertools.product(STOPS, TPS, TRAILS, BES, TIMES):
        out.append({"id": f"{sk}{sv:g}_tp{tp:g}_{tk}{tv:g}_be{be}_t{ts}", "stop": (sk, sv), "tp": tp, "trail": (tk, tv), "be": be, "time": ts})
    return out


# ---------- dados ----------
def load(data_dir, sym):
    rows = sorted(json.load(open(os.path.join(data_dir, f"candles_{sym}_60.json"))), key=lambda c: c["start"])
    return {k: np.array([float(c[k]) for c in rows]) for k in ("start", "open", "high", "low", "close", "volume")}


def atr(d, n=14):
    h, l, c = d["high"], d["low"], d["close"]; pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); out = np.full(len(c), np.nan)
    if len(c) <= n: return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)): out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n: c = np.cumsum(np.r_[0.0, x]); out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


# ---------- kernel de saída (sem look-ahead: decisões usam a vela já fechada) ----------
@njit(cache=True)
def sim_exit(o, h, l, c, a, i, e, wick, end, sk, sv, tp_r, tk, tv, be, tstop):
    """Entrada na abertura da vela i ao preço e. Devolve (net_r, j_exit, stop0, code).
    sk 0=wick 1=atr 2=pct; tk 0=none 1=chandelier(k·ATR desde máxima). Stop ≥ e·(1−8%) sempre; hard −8% do pico (regra do desk)."""
    if sk == 0: s0 = wick
    elif sk == 1: s0 = e - sv * a[i - 1]
    else: s0 = e * (1 - sv)
    s0 = max(s0, e * (1 - HARD))
    if not (s0 < e): return np.nan, i, s0, -1
    risk = e - s0; tp = e + tp_r * risk if tp_r > 0 else np.inf
    stop = s0; peak = e; hh = e; trail = -np.inf; at_be = False
    lim = MAX_HOLD if tstop == 0 else tstop
    x = np.nan; j = i; code = 0
    while j < end:
        lvl = max(stop, peak * (1 - HARD), trail)
        if o[j] <= lvl: x = o[j]; code = 1; break
        if o[j] >= tp: x = o[j]; code = 2; break
        if l[j] <= lvl: x = lvl; code = 1; break               # stop e TP na mesma vela → stop (conservador)
        if h[j] >= tp: x = tp; code = 2; break
        peak = max(peak, c[j]); hh = max(hh, h[j])
        if tk == 1: trail = hh - tv * a[j]
        if be == 1 and (not at_be) and h[j] >= e + risk: at_be = True; stop = max(stop, e)
        if j - i + 1 >= lim: x = c[j]; code = 3; break
        j += 1
    if code == 0: j = end - 1; x = c[j]; code = 4                 # fim da janela (IS cortado no SPLIT)
    fi = e * (1 + SLIP); fo = x * (1 - SLIP); fee = (fi + fo) * TAKER
    return (fo - fi - fee) / risk, j, s0, code


@njit(cache=True)
def portfolio(ent_t, ex_t, r, rfp, ok, eq0, risk, cap, maxpos):
    """Carteira realista: ≤maxpos abertas, risco 1% do equity (teto notional 15%). Trades ordenados por entrada.
    Devolve taken(bool), pnl, equity_after (por trade, na ordem de saída via ex_t)."""
    n = len(r); taken = np.zeros(n, dtype=np.bool_); pnl = np.zeros(n)
    open_ex = np.full(maxpos, np.int64(-1)); open_k = np.full(maxpos, -1); eq = eq0
    for k in range(n):
        if not ok[k]: continue
        for s in range(maxpos):                                  # fecha saídas ≤ entrada atual
            if open_k[s] >= 0 and open_ex[s] <= ent_t[k]:
                eq += pnl[open_k[s]]; open_k[s] = -1
        slot = -1
        for s in range(maxpos):
            if open_k[s] < 0: slot = s; break
        if slot < 0: continue
        dollar = min(risk * eq, cap * eq * rfp[k])
        pnl[k] = r[k] * dollar; taken[k] = True; open_k[slot] = k; open_ex[slot] = ex_t[k]
    return taken, pnl


def curve_stats(ent_t, ex_t, pnl, taken, t0, t1, eq0=EQ0):
    """DD (realizado, por ordem de saída) + retornos diários (pnl realizado no dia / equity no início do dia)."""
    idx = np.flatnonzero(taken); order = idx[np.argsort(ex_t[idx], kind="stable")]
    eq = eq0 + np.cumsum(pnl[order]) if len(order) else np.array([eq0])
    pk = np.maximum.accumulate(np.r_[eq0, eq]); dd = float(((pk - np.r_[eq0, eq]) / pk).max())
    nd = int((t1 - t0) // D); dp = np.zeros(nd)
    if len(order):
        di = np.clip((ex_t[order] - t0) // D, 0, nd - 1).astype(np.int64); np.add.at(dp, di, pnl[order])
    eq_start = eq0 + np.r_[0.0, np.cumsum(dp)[:-1]]
    return dd, dp / eq_start, float(eq[-1])


def tstats(rs):
    n = len(rs)
    if n == 0: return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0, "t": 0.0}
    m = float(np.mean(rs)); s = float(np.std(rs, ddof=1)) if n > 1 else 0.0
    return {"n": n, "win_rate": float(np.mean(rs > 0)), "expectancy_r": m, "t": m / s * math.sqrt(n) if s > 0 else 0.0}


# ---------- fase 1: entradas do desk + features ----------
def build_entries(data_dir="data_ext/coinbase"):
    from desk.replay import run
    from desk.rules import load_rules
    rules = load_rules()
    syms = sorted(f[8:-8] for f in os.listdir(data_dir) if f.startswith("candles_") and f.endswith("-USD_60.json"))
    res = run(syms, rules, data_dir)
    alerts = {(e["sym"], e["ts"]): e for e in res["events"] if e["event"] == "ALERT"}
    dat = {s: load(data_dir, s) for s in syms}
    ind = {}
    for s, d in dat.items():
        c = d["close"]; a = atr(d)
        r1 = np.r_[0.0, np.diff(np.log(c))]
        rv = np.sqrt(np.convolve(r1 ** 2, np.ones(240), "full")[:len(c)] / 240 * 24)
        v24 = np.convolve(d["volume"] * c, np.ones(24), "full")[:len(c)]
        ind[s] = {"atr": a, "sma50d": sma(c, 1200), "sma200d": sma(c, 4800), "rv10d": rv, "v24": v24, "v24m": sma(v24, 480)}
    bt = dat["BTC-USD"]; bti = {int(t): k for k, t in enumerate(bt["start"])}
    rows = []
    for t in res["trades"]:
        s = t["symbol"]; d = dat[s]; I = ind[s]; i = int(np.searchsorted(d["start"], t["entry_ts"]))
        if i < 1 or i >= len(d["start"]) or int(d["start"][i]) != t["entry_ts"]: continue
        p = i - 1; c = d["close"]; px = c[p]
        al = alerts.get((s, t["entry_ts"]), {}); zb, zt = (al.get("zone") or [np.nan, np.nan])
        bk = bti.get(int(d["start"][p]))
        bc = bt["close"]; bI = ind["BTC-USD"]
        f = {"sym": s, "entry_ts": int(t["entry_ts"]), "i": i, "entry": float(d["open"][i]), "wick": float(t["stop"]),
             "desk_r": float(t["net_r"]), "add": int(t["add"]),
             "stop_dist": (d["open"][i] - t["stop"]) / d["open"][i],
             "atr_pct": I["atr"][p] / px, "rv10d": I["rv10d"][p],
             "mom20d": px / c[p - 480] - 1 if p >= 480 else np.nan, "mom60d": px / c[p - 1440] - 1 if p >= 1440 else np.nan,
             "above_sma50d": float(px > I["sma50d"][p]) if not np.isnan(I["sma50d"][p]) else np.nan,
             "above_sma200d": float(px > I["sma200d"][p]) if not np.isnan(I["sma200d"][p]) else np.nan,
             "relvol": I["v24"][p] / I["v24m"][p] if I["v24m"][p] > 0 else np.nan,
             "zone_w": (zt - zb) / px if zt == zt else np.nan, "ent_above_zone": px / zt - 1 if zt == zt else np.nan,
             "hour": int((t["entry_ts"] // H) % 24), "weekend": float(((t["entry_ts"] // D) + 4) % 7 >= 5),
             "btc_above_sma50d": np.nan, "btc_above_sma200d": np.nan, "btc_mom20d": np.nan,
             "panel_buy": float((t.get("panel") or {}).get("action") == "BUY"),
             "panel_veto": float((t.get("panel") or {}).get("action") == "VETO"),
             "prot_block": float(bool(t.get("prot"))),
             "macro_ok": float((t.get("macro") or {}).get("status") == "OK")}
        if bk is not None:
            f["btc_above_sma50d"] = float(bc[bk] > bI["sma50d"][bk]) if not np.isnan(bI["sma50d"][bk]) else np.nan
            f["btc_above_sma200d"] = float(bc[bk] > bI["sma200d"][bk]) if not np.isnan(bI["sma200d"][bk]) else np.nan
            f["btc_mom20d"] = bc[bk] / bc[bk - 480] - 1 if bk >= 480 else np.nan
        f["hour_bucket"] = f["hour"] // 8              # 0: 00-07, 1: 08-15, 2: 16-23 UTC
        rows.append({k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in f.items()})
    return rows, dat, ind


NUMERIC = ["stop_dist", "atr_pct", "rv10d", "mom20d", "mom60d", "relvol", "zone_w", "ent_above_zone", "btc_mom20d"]
BINARY = ["above_sma50d", "above_sma200d", "btc_above_sma50d", "btc_above_sma200d", "weekend", "panel_buy", "panel_veto",
          "prot_block", "macro_ok"]
CATEG = {"hour_bucket": [0, 1, 2], "add": [0, 1]}


def candidate_filters(is_rows):
    """Limiares = tercis do IS (só IS). Cada filtro: (feature, op, valor)."""
    out = []
    for f in NUMERIC:
        v = np.array([r[f] for r in is_rows], float); v = v[~np.isnan(v)]
        if len(v) < 30: continue
        q1, q2 = np.quantile(v, [1 / 3, 2 / 3])
        out += [(f, ">=", float(q1)), (f, ">=", float(q2)), (f, "<=", float(q1)), (f, "<=", float(q2))]
    for f in BINARY: out += [(f, "==", 1.0), (f, "==", 0.0)]
    for f, vals in CATEG.items(): out += [(f, "==", float(x)) for x in vals]
    return out


def fmask(rows, flt):
    m = np.ones(len(rows), bool)
    for (f, op, v) in flt:
        x = np.array([r[f] for r in rows], float)
        with np.errstate(invalid="ignore"):
            m &= (x >= v) if op == ">=" else (x <= v) if op == "<=" else (x == v)
    return m


def sim_rows(rows, dat, ind, ex, end_ts):
    sk = {"wick": 0, "atr": 1, "pct": 2}[ex["stop"][0]]; tk = {"none": 0, "chand": 1}[ex["trail"][0]]
    R = np.full(len(rows), np.nan); J = np.zeros(len(rows), np.int64); RF = np.zeros(len(rows))
    for k, r in enumerate(rows):
        d = dat[r["sym"]]; end = int(np.searchsorted(d["start"], end_ts))
        if r["i"] >= end: continue
        nr, j, s0, code = sim_exit(d["open"], d["high"], d["low"], d["close"], ind[r["sym"]]["atr"], r["i"], r["entry"], r["wick"],
                                   end, sk, ex["stop"][1], ex["tp"], tk, ex["trail"][1], ex["be"], ex["time"])
        R[k] = nr; J[k] = int(d["start"][j]); RF[k] = (r["entry"] - s0) / r["entry"]
    return R, J, RF


def evaluate(rows, dat, ind, ex, flt, t0, t1, cache=None):
    key = ex["id"]
    if cache is not None and key in cache: R, J, RF = cache[key]
    else:
        R, J, RF = sim_rows(rows, dat, ind, ex, t1)
        if cache is not None: cache[key] = (R, J, RF)
    ent = np.array([r["entry_ts"] for r in rows], np.int64)
    ok = fmask(rows, flt) & ~np.isnan(R) & (ent >= t0) & (ent < t1)
    order = np.argsort(ent, kind="stable"); inv = np.empty_like(order); inv[order] = np.arange(len(order))
    tk, pnl = portfolio(ent[order], J[order], np.nan_to_num(R[order]), RF[order], ok[order], EQ0, RISK, CAP, MAXPOS)
    taken = tk[inv]; pnl = pnl[inv]
    dd, dly, eq_end = curve_stats(ent, J, pnl, taken, t0, t1)
    st = tstats(R[taken]); days = (t1 - t0) / D
    return {**st, "trades_per_day": st["n"] / days, "max_dd": dd, "ret": eq_end / EQ0 - 1,
            "sharpe": float(dly.mean() / dly.std(ddof=1) * math.sqrt(365)) if dly.std() > 0 else 0.0,
            "signals": int(ok.sum())}, dly


def auditor_pass(s):
    return {"n": s["n"] >= 40, "wr": s["win_rate"] >= 0.33, "exp": s["expectancy_r"] >= 0.4, "dd": s["max_dd"] <= 0.20}


# ---------- fase 1 ----------
def phase_features(data_dir):
    rows, dat, ind = build_entries(data_dir)
    os.makedirs(STATE, exist_ok=True)
    json.dump(rows, open(f"{STATE}/entries.json", "w"), default=float)
    is_rows = [r for r in rows if r["entry_ts"] < SPLIT]
    ref = {**REF_EXIT, "id": "REF"}
    R, _, _ = sim_rows(is_rows, dat, ind, ref, SPLIT)
    desk = np.array([r["desk_r"] for r in is_rows])
    rep = {"n_all": len(rows), "n_is": len(is_rows), "is_desk": tstats(desk), "is_ref_exit": tstats(R[~np.isnan(R)]), "filters": []}
    # vencedores vs perdedores (desk, IS): médias das features
    win = desk > 0
    rep["winners_vs_losers_is"] = {f: {"win_mean": float(np.nanmean([r[f] for r, w in zip(is_rows, win) if w])),
                                       "lose_mean": float(np.nanmean([r[f] for r, w in zip(is_rows, win) if not w]))}
                                   for f in NUMERIC + BINARY + ["hour", "add"]}
    for flt in candidate_filters(is_rows):
        m = fmask(is_rows, [flt]) & ~np.isnan(R)
        if m.sum() < 0.2 * len(is_rows): continue
        rep["filters"].append({"filter": list(flt), "n": int(m.sum()), "ref": tstats(R[m]), "desk": tstats(desk[m & ~np.isnan(R)])})
    rep["filters"].sort(key=lambda x: -x["ref"]["expectancy_r"])
    # escolha mecânica: top-6 por expectancy IS (saída de referência), no máx. 1 filtro por feature
    chosen, seen = [], set()
    for x in rep["filters"]:
        if x["filter"][0] in seen: continue
        chosen.append(x["filter"]); seen.add(x["filter"][0])
        if len(chosen) == 6: break
    rep["chosen_filters"] = chosen
    json.dump(rep, open(f"{STATE}/features_is.json", "w"), indent=1, default=float)
    print(json.dumps({k: rep[k] for k in ("n_all", "n_is", "is_desk", "is_ref_exit", "chosen_filters")}, indent=1, default=float))
    for x in rep["filters"][:12]: print(x["filter"], x["n"], round(x["ref"]["expectancy_r"], 3), round(x["desk"]["expectancy_r"], 3))
    return rep


def filter_options(chosen):
    ch = [tuple(c) for c in chosen]
    opts = [("none", [])] + [(f"{c[0]}{c[1]}{c[2]:.4g}", [c]) for c in ch]
    for a, b in itertools.combinations(range(min(3, len(ch))), 2):
        opts.append((f"{ch[a][0]}{ch[a][1]}{ch[a][2]:.4g}&{ch[b][0]}{ch[b][1]}{ch[b][2]:.4g}", [ch[a], ch[b]]))
    return opts


def phase_prereg():
    rep = json.load(open(f"{STATE}/features_is.json"))
    opts = filter_options(rep["chosen_filters"]); exs = exit_grid()
    doc = {"created_note": "escrito ANTES de qualquer cálculo no holdout; run recusa se o hash não bater",
           "split_ms": SPLIT, "is": [FIRST, SPLIT], "oos": [SPLIT, LAST],
           "costs": {"taker_per_side": TAKER, "slippage_per_side": SLIP}, "sizing": {"risk": RISK, "cap_notional": CAP, "max_open": MAXPOS},
           "hard_stop_pct": HARD, "max_hold_h": MAX_HOLD, "entries": "desk FVG replay (DESK_RULES atuais) sobre data_ext/coinbase, 15 pares",
           "filters": [{"id": k, "rules": v} for k, v in opts], "exits": [e["id"] for e in exs],
           "n_variants": len(opts) * len(exs),
           "selection": "IS: variantes com n_IS(carteira) >= 90; ordenar por t-stat do R líquido por trade; top-5 vão ao holdout UMA vez",
           "validation": ["OOS expectancy_r > 0 com bootstrap one-sided p < 0.05/5 (Bonferroni top-5)",
                          "DSR (Bailey-LdP) do top-1 IS > 0.95 com N = n_variants",
                          "White Reality Check IS (vs caixa, B=1000, bloco 10d) p < 0.05",
                          "DATA_VALIDATED só se as três passarem; auditor (>=40, WR>=33%, >=+0.4R, DD<=20%) reportado à parte"]}
    blob = json.dumps(doc, sort_keys=True, default=float); doc["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    json.dump(doc, open(PREREG, "w"), indent=1, default=float)
    print(doc["n_variants"], doc["sha256"]); return doc


def boot_p(rs, B=5000, seed=11):
    rng = np.random.default_rng(seed); n = len(rs)
    if n < 2: return 1.0
    c = rs - rs.mean(); m = rs.mean(); bs = c[rng.integers(n, size=(B, n))].mean(axis=1)
    return float((bs >= m).mean())


def phase_run(data_dir):
    from desk.research.sweep import deflated_sharpe, reality_check
    doc = json.load(open(PREREG)); h = doc.pop("sha256")
    assert hashlib.sha256(json.dumps(doc, sort_keys=True, default=float).encode()).hexdigest() == h, "pre-registo alterado"
    rows = json.load(open(f"{STATE}/entries.json"))
    dat = {s: load(data_dir, s) for s in sorted({r["sym"] for r in rows})}
    ind = {s: {"atr": atr(d)} for s, d in dat.items()}
    exs = {e["id"]: e for e in exit_grid()}; assert list(exs) == doc["exits"]
    opts = [(f["id"], [tuple(x) for x in f["rules"]]) for f in doc["filters"]]
    is_rows = [r for r in rows if r["entry_ts"] < SPLIT]
    cache = {}; res = {}; D_is = []
    for eid, ex in exs.items():
        for fid, flt in opts:
            s, dly = evaluate(is_rows, dat, ind, ex, flt, FIRST, SPLIT, cache)
            res[(eid, fid)] = s; D_is.append(dly)
    M = np.array(D_is); keys = list(res)
    sr_d = np.array([x.mean() / x.std(ddof=1) if x.std() > 0 else 0.0 for x in M])
    elig = [k for k in keys if res[k]["n"] >= 90]
    ranked = sorted(elig, key=lambda k: -res[k]["t"])
    top = ranked[:5]
    best_i = keys.index(top[0]) if top else int(np.argmax(sr_d))
    dsr = deflated_sharpe(M[best_i], sr_d) if M[best_i].std() > 0 else {"dsr": 0.0}
    rc = reality_check(M, B=1000)
    # ---- holdout: UMA avaliação, só top-5 + baseline desk de referência ----
    oos_rows = [r for r in rows if r["entry_ts"] >= SPLIT]; cache_o = {}
    out = []
    for k in top:
        so, _ = evaluate(oos_rows, dat, ind, exs[k[0]], dict(opts)[k[1]], SPLIT, LAST, cache_o)
        R, J, RF = cache_o[k[0]]
        p = boot_p(np.array([0.0]) if so["n"] == 0 else _taken_r(oos_rows, R, J, RF, dict(opts)[k[1]]))
        out.append({"exit": k[0], "filter": k[1], "is": res[k], "oos": {**so, "boot_p": p}, "auditor_oos": auditor_pass(so)})
    base_ex = {"id": "desk_like", "stop": ("wick", 0.0), "tp": 4.0, "trail": ("none", 0.0), "be": 1, "time": 0}
    b_is, _ = evaluate(is_rows, dat, ind, base_ex, [], FIRST, SPLIT); b_oos, _ = evaluate(oos_rows, dat, ind, base_ex, [], SPLIT, LAST)
    v1 = bool(out) and out[0]["oos"]["expectancy_r"] > 0 and out[0]["oos"]["boot_p"] < 0.01
    v2 = bool(dsr["dsr"] > 0.95); v3 = bool(rc["p"] < 0.05)
    finding = "DATA_VALIDATED" if (v1 and v2 and v3) else ("TRADE_OFF" if out and out[0]["oos"]["n"] >= 40 else "NO_EDGE")
    is_all = np.array([res[k]["expectancy_r"] for k in elig])
    rep = {"prereg_sha256": h, "n_variants": len(keys), "n_eligible": len(elig),
           "is_frac_positive_expectancy": float((is_all > 0).mean()) if len(is_all) else 0.0,
           "is_frac_t_gt_2": float(np.mean([res[k]["t"] > 2 for k in elig])) if elig else 0.0,
           "baseline_desk_like": {"is": b_is, "oos": b_oos},
           "top5": out, "dsr_top1_is": dsr, "reality_check_is": rc,
           "checks": {"oos_positive_and_significant": v1, "dsr_gt_0.95": v2, "rc_p_lt_0.05": v3}, "finding": finding,
           "is_top20": [{"exit": k[0], "filter": k[1], **res[k]} for k in ranked[:20]]}
    json.dump(rep, open(f"{STATE}/exitgrid_report.json", "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in rep.items() if k != "is_top20"}, indent=1, default=float))
    return rep


def _taken_r(rows, R, J, RF, flt):
    ent = np.array([r["entry_ts"] for r in rows], np.int64)
    ok = fmask(rows, flt) & ~np.isnan(R)
    order = np.argsort(ent, kind="stable")
    tk, _ = portfolio(ent[order], J[order], np.nan_to_num(R[order]), RF[order], ok[order], EQ0, RISK, CAP, MAXPOS)
    return R[order][tk]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=["features", "prereg", "run"])
    ap.add_argument("--data-dir", default="data_ext/coinbase"); a = ap.parse_args()
    {"features": lambda: phase_features(a.data_dir), "prereg": phase_prereg, "run": lambda: phase_run(a.data_dir)}[a.phase]()


if __name__ == "__main__":
    main()
