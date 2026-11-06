"""Especificação CONGELADA dos livros EMS (paper only) + pré-registo SHA-256 (mesmo padrão de desk/scalp/spec.py).
Mudar QUALQUER parâmetro = novo id + novo pré-registo. Resultados do forward nunca são usados para afinar.
"""
from __future__ import annotations
import hashlib, json, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREREG = os.path.join(ROOT, "desk", "research", "prereg_ems_v1.json")

SPEC = {
    "id": "ems_v1",
    "mode": "PAPER ONLY — nenhuma ordem real, nenhuma chave carregada (REVX_* removidas), nenhum caminho live",
    "origin": "zip do utilizador (prompt.md + engine Ed25519 + painel EMS) e scalp/ do Claude Code no portátil (26/10); "
              "só as técnicas aprovadas na auditoria desk/state/ems_audit.md",
    "symbols": ["BTC-USD", "ETH-USD", "SOL-USD"],
    "data": {"candles": "GET /api/1.0/public/candles/{symbol}?interval=1 (público, 1 req/s partilhado via desk/scalp/feed)",
             "order_book": "GET /api/2.0/public/order-book/{symbol}?limit=10 (público; ≤20 pedidos/10 s; usamos 3/min)",
             "close_grace_s": 20, "missing_minute": "O=H=L=C=fecho anterior, v=0 (sintética)", "catchup_age_s": 180},
    "indicators": {"vwap_n": 60, "vwap_price": "típico (h+l+c)/3 ponderado pelo volume", "rsi_n": 14, "atr_n": 14,
                   "bb_n": 20, "bb_k": 2.0, "squeeze_lookback": 120, "squeeze_pct": 0.20, "vol_n": 20,
                   "div_lookback": 30, "warmup_bars": 150, "obi_depth": 5},
    "filters": {"atr_min_bps": 3.0, "atr_max_bps": 120.0,
                "shock": "|retorno da vela| > 4 × ATR → sem entradas por 15 velas", "shock_ret_atr": 4.0, "shock_cooldown_bars": 15,
                "macro": "desk.macro.evaluate no fecho da vela (ponto-no-tempo, sem look-ahead): RISK_OFF → sem entradas; "
                         "CAUTION/OK/INSUFFICIENT_DATA → permitido", "news_llm": "não usado (sem fonte paga, sem histórico validável)"},
    "books": {
        "ems_vwap_mr": {"name": "EMS VWAP-Reversão 1m", "entry": "close ≤ VWAP60 × (1 − 1,5 × ATR%) e RSI14 ≤ 30 e close > open",
                        "vwap_dev_atr": 1.5, "rsi_max": 30.0, "time_stop_bars": 30, "needs_book": False, "entry_mode": "maker"},
        "ems_vwap_obi": {"name": "EMS VWAP-Reversão + OBI L2", "entry": "igual a ems_vwap_mr E livro L2 ao vivo: OBI(top5) ≥ 0,20 e spread ≤ 8 bps",
                         "vwap_dev_atr": 1.5, "rsi_max": 30.0, "obi_min": 0.20, "max_spread_bps": 8.0, "book_max_age_s": 120,
                         "time_stop_bars": 30, "needs_book": True, "entry_mode": "maker",
                         "catchup": "sem L2 histórico → nenhuma entrada em velas de catchup (rej_no_book); a ordem só fica activa "
                                    "a partir do minuto seguinte à leitura do livro (sem look-ahead)"},
        "ems_rsi_div": {"name": "EMS RSI micro-divergência 1m",
                        "entry": "low < mínimo dos lows das 30 velas anteriores, RSI14 actual ≥ RSI nesse mínimo + 3, RSI14 ≤ 40, close > open",
                        "div_rsi_gap": 3.0, "rsi_max": 40.0, "time_stop_bars": 30, "needs_book": False, "entry_mode": "maker"},
        "ems_squeeze_bo": {"name": "EMS BB-Squeeze Breakout 1m",
                           "entry": "largura BB(20,2) da vela anterior ≤ percentil 20 das 120 anteriores; close > banda alta; "
                                    "volume > 1,2 × média das 20 anteriores e > 0",
                           "vol_mult": 1.2, "time_stop_bars": 60, "needs_book": False, "entry_mode": "taker_if_edge"},
    },
    "execution": {"maker_first": "limite post-only ao bid (close × (1 − meio-spread)), válida 3 velas, enche só se uma vela "
                                 "seguinte ATRAVESSAR (low < limite) — proxy conservador de fila; preço = limite; taxa 0",
                  "entry_policy": "reversões (vwap_mr, vwap_obi, rsi_div) entram SEMPRE com limite maker; só o breakout (squeeze_bo, entry_mode taker_if_edge) pode ir a mercado",
                  "taker_rule": "entrada a mercado só se alvo% − custo ida-e-volta taker > 0,35%; enche na abertura da vela seguinte × "
                                "(1 + slippage + meio-spread), taxa 0,09%",
                  "taker_min_edge": 0.0035, "entry_valid_bars": 3,
                  "tp_exit": "limite maker no alvo (high > alvo), taxa 0, nunca na vela do enchimento",
                  "stop_exit": "taker: low ≤ stop → min(stop, open) × (1 − slippage − meio-spread), taxa 0,09%",
                  "same_bar": "stop e alvo na mesma vela → stop; entrada e stop na mesma vela → stop",
                  "time_exit": "taker ao fecho × (1 − slippage − meio-spread), taxa 0,09%",
                  "maker_fee": "0", "taker_fee": "0.0009", "slippage": "0.0010", "slippage_note": "10 bps (meio da faixa 5–15 bps)",
                  "half_spread": "forward: livro público ≤120 s; senão valor fixo", "fallback_half_spread": {"BTC-USD": "0.00008", "ETH-USD": "0.00010", "SOL-USD": "0.00019"},
                  "latency": "decisão no fecho da vela; ordem elegível a partir da vela seguinte (≥ latência real de ~1,5 s)"},
    "risk": {"start_equity": "65", "risk_pct": "0.01", "stop": "d = min(max(1,5 × ATR%, 0,30%), 1,50%)",
             "stop_atr_mult": 1.5, "stop_min": 0.0030, "stop_max": 0.0150, "rr": 2.0, "tp": "entrada × (1 + 2d)",
             "cost_rt_maker": "taker + slippage + 2 × meio-spread", "cost_rt_taker": "2 × (taker + slippage + meio-spread)",
             "reject_if": "alvo% ≤ custo ida-e-volta (alvo não paga os custos)",
             "R_unit": "qty × (entrada − stop) + qty × stop × (taker + slippage + meio-spread)",
             "pos_cap_frac": "0.33", "max_open": 3, "one_per_symbol": True, "min_notional": "1", "qty_step": "0.00000001",
             "dd_kill": "0.20", "dd_kill_rule": "queda > 20% do pico (marcada) → HALTED_MAX_DRAWDOWN trancado (fecha tudo, taker)",
             "ceiling": "1000", "ceiling_rule": "equity ≥ $1.000 → CEILING_PAUSED trancado (fecha tudo); volta a $65 só com rebase MANUAL "
                                                "ordenado pelo utilizador (python -m desk.ems rebase <livro> --confirm)",
             "money": "Decimal em caixa, PnL, taxas e tamanhos; indicadores em float (só decidem)",
             "never": "nunca deposita, nunca levanta, sem vault $800, sem alavancagem, só long spot"},
    "states": ["PAPER_TRAINING", "HALTED_MAX_DRAWDOWN", "CEILING_PAUSED"],
    "auditor": {"min_trades": 40, "win_rate": 0.33, "expectancy_r": 0.4, "max_dd": 0.20,
                "verdict": "cada livro precisa dos SEUS 40 trades; <40 → dados insuficientes; todos OK → possível GO (só paper); senão NO-GO"},
    "no_tuning": "parâmetros congelados; nunca forçar trades; resultados nunca mudam parâmetros",
}


def canon(obj) -> str: return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def spec_hash(spec=None) -> str: return hashlib.sha256(canon(SPEC if spec is None else spec).encode()).hexdigest()


def code_hash() -> str:
    h = hashlib.sha256(); d = os.path.dirname(os.path.abspath(__file__))
    for f in ("ind.py", "engine.py", "spec.py"):
        h.update(open(os.path.join(d, f), "rb").read())
    return h.hexdigest()


def freeze(path=PREREG, force=False) -> dict:
    if os.path.exists(path) and not force: raise RuntimeError("pré-registo já existe; não reescrevo (mudança = novo id)")
    doc = {"note": "escrito ANTES de correr o forward; o runner recusa se o spec ou o hash divergirem",
           "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spec": SPEC, "sha256": spec_hash(),
           "code_sha256_at_freeze": code_hash()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def check(path=PREREG) -> str:
    if not os.path.exists(path): raise RuntimeError("sem pré-registo: corre `python -m desk.ems prereg` primeiro")
    doc = json.load(open(path))
    if doc.get("sha256") != spec_hash(doc.get("spec")) or doc["sha256"] != spec_hash():
        raise RuntimeError("spec diverge do pré-registo congelado — recuso correr (mudança exige novo id/pré-registo)")
    return doc["sha256"]
