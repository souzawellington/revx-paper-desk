"""Especificação CONGELADA dos livros NEWS (paper only) + pré-registo SHA-256 (mesmo padrão de desk/ems/spec.py).
Mudar QUALQUER parâmetro = novo id + novo pré-registo. Resultados do forward nunca são usados para afinar.
"""
from __future__ import annotations
import hashlib, json, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREREG = os.path.join(ROOT, "desk", "research", "prereg_news_v1.json")

SPEC = {
    "id": "news_v1",
    "mode": "PAPER ONLY — nenhuma ordem real, nenhuma chave (REVX_* removidas do processo), nenhum caminho live, nenhum broker",
    "origin": "pedido do utilizador 28/10/2026 (bot de notícias); só fontes públicas grátis, sem chaves pagas, sem X/Twitter",
    "universe": {"source": "GET /api/1.0/public/tickers (Revolut X, público) — região UK, cotação USD",
                 "exclude_stables": ["USDT", "USDC", "DAI", "EURC", "RLUSD", "PYUSD", "FDUSD", "TUSD", "USDE", "USDS", "USD1", "GBPT", "EURT", "USDG", "XAUT", "PAXG"],
                 "min_quote_vol_24h_usd": 10000.0, "max_spread_bps": 40.0},
    "sources": {
        "rss": {"cointelegraph": "https://cointelegraph.com/rss", "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
                "theblock": "https://www.theblock.co/rss.xml", "decrypt": "https://decrypt.co/feed", "cryptoslate": "https://cryptoslate.com/feed/"},
        "listings": {"binance_new_listing": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20",
                     "binance_delisting": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=161&pageNo=1&pageSize=20"},
        "trending": {"coingecko": "https://api.coingecko.com/api/v3/search/trending"},
        "names": {"coingecko_markets": "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={p} (p=1,2; cache 24 h)"},
        "poll_s": {"rss": 180, "listings": 300, "trending": 600, "names": 86400},
        "x_twitter": "não usado (sem fonte pública sem chave)",
    },
    "nlp": {
        "text": "título + primeiros 400 caracteres do resumo (HTML removido)",
        "entities": "(a) $SYM ou (SYM) em maiúsculas; (b) palavra toda em maiúsculas = símbolo do universo, ≥3 letras, fora da stoplist; "
                    "(c) nome do projeto (CoinGecko top-500 + aliases fixos), ≥5 letras, fora da lista de palavras comuns; "
                    "só conta se o símbolo estiver no universo Revolut X",
        "sentiment": "léxico fixo (POS/NEG em desk/news/sources.py); score = nº de termos POS distintos − nº de NEG distintos, limitado a ±3",
        "listing_bonus": 2, "delisting_score": -3,
        "positive_min": 1, "negative_veto_max": -1, "negative_veto_h": 6,
        "item_max_age_min": 90, "window_min": 60,
        "trending_bonus": 1, "trending_alone": "nunca dispara sozinho (precisa de ≥1 notícia positiva)",
        "on_start": "itens já publicados no 1.º ciclo ficam 'baseline_on_start' e nunca são negociados",
        "max_candidates_per_cycle": 6,
    },
    "market": {"bars": "velas 5m públicas da Revolut X, últimas 24 h (só velas fechadas)",
               "vol_ratio": "volume das últimas 3 velas 5m ÷ (3 × média das velas 5m anteriores nas 24 h)",
               "mom_15m": "fecho agora ÷ fecho de 3 velas atrás − 1",
               "runup_since_news": "fecho agora ÷ abertura da vela 5m em que a notícia foi publicada − 1 (anti-topo)",
               "chg_24h": "fecho agora ÷ fecho de 24 h atrás − 1", "atr_n": 14, "min_bars": 150,
               "macro": "desk.macro.evaluate ponto-no-tempo (1×/hora): RISK_OFF → sem entradas"},
    "books": {
        "news_momo": {"name": "NEWS Momentum confirmado", "entry_mode": "taker",
                      "rule": "notícia positiva (score ≥1) + vol_ratio ≥2,0 + mom_15m entre +0,3% e +3,0% + subida desde a notícia ≤3% "
                              "+ 24 h ≤ +12% → compra a mercado na abertura do minuto seguinte",
                      "min_vol_ratio": 2.0, "mom_min": 0.003, "mom_max": 0.03, "max_runup": 0.03, "max_chg_24h": 0.12,
                      "min_edge": 0.005, "time_stop_min": 240},
        "news_pullback": {"name": "NEWS Pullback maker", "entry_mode": "maker",
                          "rule": "notícia positiva (score ≥1) + vol_ratio ≥1,5 + mom_15m ≥0 + subida desde a notícia ≤5% + 24 h ≤ +15% "
                                  "→ limite maker a fecho × (1 − d/2), válida 30 min; só enche se uma vela 1m seguinte ATRAVESSAR o limite",
                          "min_vol_ratio": 1.5, "mom_min": 0.0, "mom_max": None, "max_runup": 0.05, "max_chg_24h": 0.15,
                          "pullback_frac_of_stop": 0.5, "valid_min": 30, "min_edge": 0.003, "time_stop_min": 240},
    },
    "execution": {"decision": "no ciclo (~120 s) com velas 5m fechadas + tickers públicos; ordem elegível só a partir do minuto seguinte",
                  "taker_fill": "abertura da 1.ª vela 1m depois da decisão × (1 + slippage + meio-spread), taxa 0,09%",
                  "maker_fill": "preço limite, taxa 0, só se low de uma vela 1m seguinte < limite",
                  "tp_exit": "limite maker no alvo (high > alvo), taxa 0, nunca na vela do enchimento",
                  "stop_exit": "taker: low ≤ stop → min(stop, open) × (1 − slippage − meio-spread), taxa 0,09%",
                  "same_bar": "stop e alvo na mesma vela → stop", "time_exit": "taker ao fecho × (1 − slippage − meio-spread), taxa 0,09%",
                  "maker_fee": "0", "taker_fee": "0.0009", "slippage": "0.0010",
                  "half_spread": "dos tickers públicos (bid/ask) no momento; fallback 0.0020"},
    "risk": {"start_equity": "65", "risk_pct": "0.01", "stop": "d = min(max(2 × ATR14(5m)%, 0,80%), 4,00%)",
             "stop_atr_mult": 2.0, "stop_min": 0.008, "stop_max": 0.04, "rr": 2.0,
             "cost_rt": "2 × (taker + slippage + meio-spread) no momentum; taker + slippage + 2 × meio-spread no pullback",
             "reject_if": "alvo% − custo ida-e-volta < min_edge do livro",
             "pos_cap_frac": "0.33", "max_open": 3, "one_per_symbol": True, "cooldown_h": 6, "min_notional": "1",
             "qty_step": "0.00000001", "dd_kill": "0.20", "ceiling": "1000",
             "dd_kill_rule": "queda > 20% do pico (marcada) → HALTED_MAX_DRAWDOWN trancado (fecha tudo)",
             "ceiling_rule": "equity ≥ $1.000 → CEILING_PAUSED trancado; volta a $65 só com `python -m desk.news rebase <livro> --confirm` (decisão do utilizador)",
             "never": "nunca deposita, nunca levanta, sem alavancagem, só long spot"},
    "states": ["PAPER_TRAINING", "HALTED_MAX_DRAWDOWN", "CEILING_PAUSED"],
    "audit_log": "cada notícia considerada → news_items.jsonl (moedas, score, decisão); cada avaliação de moeda → signals.jsonl (métricas + motivo)",
    "auditor": {"min_trades": 40, "win_rate": 0.33, "expectancy_r": 0.4, "max_dd": 0.20},
    "no_tuning": "parâmetros congelados; nunca forçar trades; resultados nunca mudam parâmetros",
}


def canon(obj) -> str: return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def spec_hash(spec=None) -> str: return hashlib.sha256(canon(SPEC if spec is None else spec).encode()).hexdigest()


def code_hash() -> str:
    h = hashlib.sha256(); d = os.path.dirname(os.path.abspath(__file__))
    for f in ("sources.py", "engine.py", "spec.py"):
        h.update(open(os.path.join(d, f), "rb").read())
    return h.hexdigest()


def freeze(path=PREREG, force=False) -> dict:
    if os.path.exists(path) and not force: raise RuntimeError("pré-registo já existe; não reescrevo (mudança = novo id)")
    doc = {"note": "escrito ANTES do primeiro trade; o runner recusa se o spec ou o hash divergirem",
           "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spec": SPEC, "sha256": spec_hash(),
           "code_sha256_at_freeze": code_hash()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def check(path=PREREG) -> str:
    if not os.path.exists(path): raise RuntimeError("sem pré-registo: corre `python -m desk.news prereg` primeiro")
    doc = json.load(open(path))
    if doc.get("sha256") != spec_hash(doc.get("spec")) or doc["sha256"] != spec_hash():
        raise RuntimeError("spec diverge do pré-registo congelado — recuso correr (mudança exige novo id/pré-registo)")
    return doc["sha256"]
