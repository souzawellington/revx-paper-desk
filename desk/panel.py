"""ANALYST PANEL (repo virattt/ai-hedge-fund, MIT; adaptado a cripto spot Revolut X).

Ideia trazida do repo: vários analistas independentes avaliam o MESMO alerta por ângulos diferentes
(tendência, momentum, reversão à média, volatilidade, regime do mercado) e cada um devolve
bullish/neutral/bearish + confiança; um consenso ponderado por peso×confiança decide. Do risk_manager do repo:
redução por correlação com posições abertas e teto de notional ajustado à volatilidade.

Diferenças obrigatórias (DESK_RULES.md):
- Determinístico, sem LLM e sem chamadas pagas. Só usa velas FECHADAS (sem look-ahead).
- O painel só pode VETAR ou REDUZIR: size_mult ∈ [0, 1], nunca > 1. Os aumentos do repo
  (correlação baixa → 1.05/1.10×, vol baixa → 25%) foram removidos.
- Dados em falta ⇒ o analista ABSTÉM-SE (INSUFFICIENT_DATA). Com menos de panel_min_votes votos válidos,
  o painel não tem opinião e não altera nada (nunca aumenta por falta de dados).
- Personas de ações (Buffett, Graham, Munger, Lynch…) e P/E, insider trades, earnings: não se aplicam a cripto.
- Hook LLM opcional e DESLIGADO (panel_llm_hook: false); se ligado, recebe texto via untrusted_wrap e o
  seu resultado é limitado a vetar/reduzir (clamp_llm).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict

BULL, NEUT, BEAR, ABST = "bullish", "neutral", "bearish", "INSUFFICIENT_DATA"
NUM = {BULL: 1.0, NEUT: 0.0, BEAR: -1.0}
DEFAULT_WEIGHTS = {"trend_4h": 0.25, "momentum_1d": 0.25, "mean_reversion_4h": 0.20, "volatility_1d": 0.15, "btc_regime_1d": 0.15}


@dataclass
class Vote:
    analyst: str
    signal: str
    confidence: float = 0.0
    metrics: dict = field(default_factory=dict)


# ---------------- indicadores (puro Python) ----------------
def ema(xs, n):
    if len(xs) < n: return []
    k = 2 / (n + 1); out = [sum(xs[:n]) / n]
    for x in xs[n:]: out.append(x * k + out[-1] * (1 - k))
    return out


def _std(xs):
    if len(xs) < 2: return 0.0
    m = sum(xs) / len(xs); return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def adx(c, n=14):
    """ADX de Wilder sobre velas {high,low,close}. None se dados insuficientes."""
    if len(c) < 2 * n + 1: return None
    tr, pdm, mdm = [], [], []
    for a, b in zip(c[:-1], c[1:]):
        up, dn = b["high"] - a["high"], a["low"] - b["low"]
        pdm.append(up if up > dn and up > 0 else 0.0); mdm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])))
    def wilder(xs):
        s = [sum(xs[:n])]
        for x in xs[n:]: s.append(s[-1] - s[-1] / n + x)
        return s
    atr_, p_, m_ = wilder(tr), wilder(pdm), wilder(mdm)
    dx = []
    for t, p, m in zip(atr_, p_, m_):
        if t <= 0: dx.append(0.0); continue
        pdi, mdi = 100 * p / t, 100 * m / t
        dx.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    if len(dx) < n: return None
    a = sum(dx[:n]) / n
    for x in dx[n:]: a = (a * (n - 1) + x) / n
    return a


def returns(closes): return [b / a - 1 for a, b in zip(closes[:-1], closes[1:]) if a > 0]


# ---------------- analistas ----------------
def trend_4h(h4, **_):
    cl = [x["close"] for x in h4]
    e8, e21, e55 = ema(cl, 8), ema(cl, 21), ema(cl, 55); a = adx(h4, 14)
    if not e55 or a is None: return Vote("trend_4h", ABST, 0.0, {"bars": len(h4)})
    s, m = e8[-1] > e21[-1], e21[-1] > e55[-1]
    sig = BULL if s and m else BEAR if (not s and not m) else NEUT
    return Vote("trend_4h", sig, a / 100 if sig != NEUT else 0.5, {"adx": round(a, 2)})


def momentum_1d(d1, **_):
    """Repo: 0.4·1m + 0.3·3m + 0.3·6m (dias úteis). Cripto (24/7): 7/21/42 dias."""
    if len(d1) < 43: return Vote("momentum_1d", ABST, 0.0, {"bars": len(d1)})
    cl = [x["close"] for x in d1]; vol = [x.get("volume", 0.0) for x in d1]
    r = lambda k: cl[-1] / cl[-1 - k] - 1
    score = 0.4 * r(7) + 0.3 * r(21) + 0.3 * r(42)
    vma = sum(vol[-21:]) / 21
    vconf = vma > 0 and vol[-1] > vma
    if score > 0.05 and vconf: sig = BULL
    elif score < -0.05 and vconf: sig = BEAR
    else: sig = NEUT
    return Vote("momentum_1d", sig, min(abs(score) * 5, 1.0) if sig != NEUT else 0.5,
                {"score": round(score, 4), "volume_confirm": bool(vconf)})


def mean_reversion_4h(h4, **_):
    if len(h4) < 50: return Vote("mean_reversion_4h", ABST, 0.0, {"bars": len(h4)})
    cl = [x["close"] for x in h4]
    w50 = cl[-50:]; ma, sd = sum(w50) / 50, _std(w50)
    w20 = cl[-20:]; m20, s20 = sum(w20) / 20, _std(w20)
    if sd <= 0 or s20 <= 0: return Vote("mean_reversion_4h", ABST, 0.0, {"why": "std=0"})
    z = (cl[-1] - ma) / sd; up, lo = m20 + 2 * s20, m20 - 2 * s20
    bb = (cl[-1] - lo) / (up - lo)
    if z < -2 and bb < 0.2: sig = BULL
    elif z > 2 and bb > 0.8: sig = BEAR
    else: sig = NEUT
    return Vote("mean_reversion_4h", sig, min(abs(z) / 4, 1.0) if sig != NEUT else 0.5, {"z": round(z, 3), "bb_pos": round(bb, 3)})


def volatility_1d(d1, **_):
    """Repo: vol 21 vs média 63. Cripto anualiza com 365."""
    if len(d1) < 21 + 63 + 1: return Vote("volatility_1d", ABST, 0.0, {"bars": len(d1)})
    rets = returns([x["close"] for x in d1])
    hv = [_std(rets[i - 21:i]) * math.sqrt(365) for i in range(21, len(rets) + 1)]
    if len(hv) < 63: return Vote("volatility_1d", ABST, 0.0, {"bars": len(d1)})
    w = hv[-63:]; vma, vsd = sum(w) / 63, _std(w)
    if vma <= 0 or vsd <= 0: return Vote("volatility_1d", ABST, 0.0, {"why": "std=0"})
    reg, vz = hv[-1] / vma, (hv[-1] - vma) / vsd
    if reg < 0.8 and vz < -1: sig = BULL
    elif reg > 1.2 and vz > 1: sig = BEAR
    else: sig = NEUT
    return Vote("volatility_1d", sig, min(abs(vz) / 3, 1.0) if sig != NEUT else 0.5,
                {"ann_vol": round(hv[-1], 4), "regime": round(reg, 3), "vol_z": round(vz, 3)})


def btc_regime_1d(btc_d1=None, **_):
    """Novo (cripto): regime do mercado = BTC vs EMA50 1D e inclinação da EMA20 (5 dias)."""
    if not btc_d1 or len(btc_d1) < 55: return Vote("btc_regime_1d", ABST, 0.0, {"bars": len(btc_d1 or [])})
    cl = [x["close"] for x in btc_d1]; e50, e20 = ema(cl, 50), ema(cl, 20)
    above, rising = cl[-1] > e50[-1], e20[-1] > e20[-6]
    sig = BULL if above and rising else BEAR if (not above and not rising) else NEUT
    dist = abs(cl[-1] / e50[-1] - 1)
    return Vote("btc_regime_1d", sig, min(dist * 10, 1.0) if sig != NEUT else 0.5,
                {"btc_vs_ema50": round(cl[-1] / e50[-1] - 1, 4), "ema20_rising": bool(rising)})


ANALYSTS = {"trend_4h": trend_4h, "momentum_1d": momentum_1d, "mean_reversion_4h": mean_reversion_4h,
            "volatility_1d": volatility_1d, "btc_regime_1d": btc_regime_1d}


# ---------------- redutores do risk_manager do repo (só reduzem) ----------------
def correlation_mult(cand_d1, open_d1s: list, lookback=60):
    """Média da correlação dos retornos 1D com as posições abertas: ≥0.8→0.70, ≥0.6→0.85, senão 1.0 (sem aumentos)."""
    if not open_d1s: return 1.0, None
    def corr(a, b):
        n = min(len(a), len(b), lookback)
        if n < 20: return None
        a, b = a[-n:], b[-n:]; ma, mb = sum(a) / n, sum(b) / n
        sa, sb = math.sqrt(sum((x - ma) ** 2 for x in a)), math.sqrt(sum((y - mb) ** 2 for y in b))
        return None if sa == 0 or sb == 0 else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)
    ra = returns([x["close"] for x in cand_d1])
    cs = [c for c in (corr(ra, returns([x["close"] for x in d])) for d in open_d1s) if c is not None]
    if not cs: return 1.0, None
    avg = sum(cs) / len(cs)
    return (0.70 if avg >= 0.8 else 0.85 if avg >= 0.6 else 1.0), round(avg, 3)


def vol_cap_frac(ann_vol, max_position_frac):
    """Repo: limite 20%×mult(vol). Aqui nunca acima de max_position_frac (15%)."""
    if ann_vol is None: return max_position_frac
    if ann_vol < 0.15: m = 1.25
    elif ann_vol < 0.30: m = 1.0 - (ann_vol - 0.15) * 0.5
    elif ann_vol < 0.50: m = 0.75 - (ann_vol - 0.30) * 0.5
    else: m = 0.50
    return min(max_position_frac, 0.20 * max(0.25, min(1.25, m)))


def clamp_llm(current_mult: float, llm_mult) -> float:
    """Hook LLM: só pode igualar ou reduzir o multiplicador atual."""
    try: x = float(llm_mult)
    except (TypeError, ValueError): return current_mult
    if math.isnan(x): return current_mult
    return max(0.0, min(current_mult, x))


# ---------------- consenso ----------------
def p(rules, k, d):
    try: return rules.p.get(k, d)
    except AttributeError: return d


def evaluate(rules, h4, d1, btc_d1=None, open_d1s=None, llm=None):
    """Devolve dict JSON-serializável: votes, score, consensus, action (KEEP|REDUCE|VETO|NO_OPINION), size_mult ≤ 1,
    notional_cap_frac. NUNCA aumenta tamanho."""
    W = dict(DEFAULT_WEIGHTS)
    votes = [fn(h4=h4, d1=d1, btc_d1=btc_d1) for name, fn in ANALYSTS.items()]
    valid = [v for v in votes if v.signal != ABST]
    num = sum(NUM[v.signal] * W[v.analyst] * v.confidence for v in valid)
    den = sum(W[v.analyst] * v.confidence for v in valid)
    score = num / den if den > 0 else 0.0
    th = float(p(rules, "panel_consensus_threshold", 0.2))
    min_votes = int(p(rules, "panel_min_votes", 3))
    if len(valid) < min_votes:
        cons, action, mult = ABST, "NO_OPINION", 1.0
    else:
        cons = BULL if score > th else BEAR if score < -th else NEUT
        if cons == BEAR: action, mult = "VETO", 0.0
        elif cons == NEUT:
            mult = min(1.0, max(0.0, float(p(rules, "panel_neutral_mult", 0.5))))
            action = "REDUCE" if mult < 1 else "KEEP"
        else: action, mult = "KEEP", 1.0
    cm, avg_corr = correlation_mult(d1, open_d1s or []) if d1 else (1.0, None)
    if mult > 0 and cm < 1: mult *= cm; action = "REDUCE" if action in ("KEEP", "NO_OPINION") else action
    volv = next((v for v in votes if v.analyst == "volatility_1d"), None)
    ann = (volv.metrics or {}).get("ann_vol") if volv else None
    if ann is None and d1 and len(d1) > 22:
        ann = _std(returns([x["close"] for x in d1])[-21:]) * math.sqrt(365)
    cap = vol_cap_frac(ann, float(rules.max_position_frac)) if p(rules, "panel_vol_cap", True) else float(rules.max_position_frac)
    if llm is not None and p(rules, "panel_llm_hook", False):
        mult = clamp_llm(mult, llm)
        if mult == 0: action = "VETO"
    mult = max(0.0, min(1.0, mult))
    assert mult <= 1.0 and cap <= float(rules.max_position_frac) + 1e-12
    return {"votes": [asdict(v) for v in votes], "valid_votes": len(valid), "score": round(score, 4), "consensus": cons,
            "action": action, "size_mult": round(mult, 4), "corr_mult": cm, "avg_corr": avg_corr,
            "notional_cap_frac": round(cap, 4), "mode": p(rules, "panel_mode", "shadow")}


def apply(qty, entry, equity, decision, rules):
    """Aplica a decisão a uma quantidade: só reduz. Devolve (qty_nova, nota)."""
    mode = p(rules, "panel_mode", "shadow")
    if mode != "enforce": return qty, f"panel {mode}: sem efeito"
    q = qty * min(1.0, decision["size_mult"])
    cap_q = decision["notional_cap_frac"] * equity / entry if entry > 0 else q
    q2 = min(q, cap_q)
    return min(qty, q2), ("panel_vol_cap" if q2 < q else "panel" if q < qty else "unchanged")


def summary(decision) -> str:
    short = {BULL: "▲", NEUT: "•", BEAR: "▼", ABST: "?"}
    vs = " ".join(f"{v['analyst']}{short[v['signal']]}{v['confidence']:.2f}" for v in decision["votes"])
    return (f"Painel ({decision['mode']}): {decision['consensus']} score {decision['score']:+.2f} → {decision['action']} "
            f"×{decision['size_mult']:.2f} | cap vol {decision['notional_cap_frac']:.0%} | {vs}")
