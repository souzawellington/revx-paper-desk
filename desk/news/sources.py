"""Fontes PÚBLICAS de notícias (sem chaves) + extração de moedas + sentimento por léxico fixo (congelado com o spec).
Funções puras (parse_*, entities, sentiment, score_item) são testadas offline; fetch_* recebem um `get_text` injectável.
Todo o texto vindo da internet é DADO não confiável: só é lido para contar palavras, nunca executado nem seguido.
"""
from __future__ import annotations
import hashlib, html, json, re, time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (paper-research-bot; read-only)", "Accept": "*/*"}

# ---------------- léxico (congelado: mudar = novo id) ----------------
POS = {
    "surge": r"surg(e|es|ed|ing)", "soar": r"soar(s|ed|ing)?", "rally": r"rall(y|ies|ied|ying)", "jump": r"jump(s|ed|ing)?",
    "spike": r"spik(e|es|ed|ing)", "climb": r"climb(s|ed|ing)?", "rebound": r"rebound(s|ed|ing)?", "breakout": r"break(s|ing)? ?out",
    "record": r"(record|all-time) high|\bath\b", "bullish": r"bullish", "inflow": r"inflows?", "approve": r"approv(e|es|ed|al)",
    "listing": r"(will |to )?list(s|ed|ing)? on|listing|will list", "launch": r"launch(es|ed|ing)?", "partner": r"partner(s|ship|ships|ed)?",
    "integrate": r"integrat(e|es|ed|ion)", "adopt": r"adopt(s|ed|ion)?", "upgrade": r"upgrad(e|es|ed)", "mainnet": r"mainnet",
    "buyback": r"buy-?backs?", "burn": r"burn(s|ed)?", "acquire": r"acqui(re|res|red|sition)", "accumulate": r"accumulat(e|es|ed|ion)",
    "gain": r"gain(s|ed)?", "rise": r"ris(e|es|ing)|rose", "investment_grade": r"investment-grade",
}
NEG = {
    "hack": r"hack(s|ed|er|ers)?", "exploit": r"exploit(s|ed)?", "drain": r"drain(s|ed)?", "breach": r"breach(es|ed)?",
    "leak": r"leak(s|ed)?", "lawsuit": r"lawsuits?|sues?d?|suing", "charge": r"charg(e|es|ed) (with|against)|indict",
    "fraud": r"fraud|scam|rug ?pull|ponzi", "delist": r"delist(s|ed|ing)?|removal of", "crash": r"crash(es|ed)?",
    "plunge": r"plung(e|es|ed)|plummet(s|ed)?|tumbl(e|es|ed)|sink(s)?|sank|slump(s|ed)?|dump(s|ed)?", "drop": r"drop(s|ped)?|fall(s|en)?|fell|declin(e|es|ed)",
    "outflow": r"outflows?", "ban": r"bans?|banned", "bearish": r"bearish", "liquidation": r"liquidat(e|ed|ion|ions)",
    "probe": r"investigat(e|es|ion)|probe", "halt": r"halt(s|ed)?|suspend(s|ed)?|outage", "unlock": r"unlocks?",
    "selloff": r"sell-?off", "warn": r"warn(s|ed|ing)?", "insolvency": r"insolv|bankrupt",
}
_POS = {k: re.compile(r"\b(" + v + r")\b", re.I) for k, v in POS.items()}
_NEG = {k: re.compile(r"\b(" + v + r")\b", re.I) for k, v in NEG.items()}

STOP_UPPER = {"ETF", "ETFS", "SEC", "USD", "CEO", "CFO", "CTO", "COO", "USA", "IPO", "DEX", "CEX", "NFT", "NFTS", "DAO", "API", "GDP",
              "CPI", "FED", "FOMC", "IMF", "ATH", "TVL", "OTC", "KYC", "AML", "DOJ", "CFTC", "FBI", "IRS", "LLC", "THE", "AND", "FOR",
              "NEW", "NOT", "ALL", "ONE", "TOP", "BIG", "WIN", "HOT", "GAS", "KEY", "ANY", "NOW", "CAT", "DOG", "BTC'S", "ETH'S",
              "MICA", "ESMA", "FCA", "OCC", "FDIC", "ECB", "BOE", "BOJ", "PBOC", "EUR", "GBP", "JPY", "CNY", "AI", "UK", "US", "EU",
              "Q1", "Q2", "Q3", "Q4", "RWA", "DEFI", "CEFI", "PNL", "APY", "APR", "ROI", "YTD", "MOM", "WOW", "OMG", "LOL", "IMO",
              "POW", "POS", "L1", "L2", "ZK", "EVM", "SDK", "TPS", "MEV", "LST", "LRT", "SPOT", "BUY", "SELL", "LONG", "SHORT",
              "BOND", "EDGE", "REAL", "LINK"}  # LINK só por nome (Chainlink) ou $LINK/(LINK): palavra comum em títulos
ALIASES = {"bitcoin": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL", "ripple": "XRP", "dogecoin": "DOGE",
           "cardano": "ADA", "chainlink": "LINK", "litecoin": "LTC", "polkadot": "DOT", "avalanche": "AVAX", "shiba inu": "SHIB",
           "toncoin": "TON", "uniswap": "UNI", "aave": "AAVE", "sui": "SUI", "aptos": "APT", "arbitrum": "ARB", "hedera": "HBAR",
           "injective": "INJ", "celestia": "TIA", "near protocol": "NEAR", "pepe": "PEPE", "hyperliquid": "HYPE", "ondo": "ONDO",
           "bitcoin cash": "BCH", "zcash": "ZEC", "monero": "XMR", "tron": "TRX", "polygon": "POL", "worldcoin": "WLD",
           "render": "RENDER", "ethena": "ENA", "pudgy penguins": "PENGU", "bonk": "BONK", "algorand": "ALGO", "kaspa": "KAS"}
COMMON_NAMES = {"stellar", "cosmos", "optimism", "immutable", "maker", "flow", "harmony", "oasis", "origin", "dash", "theta",
                "core", "celo", "status", "civic", "power", "storj", "loom", "gala", "blur", "magic", "space", "quant", "ronin",
                "access", "story", "sonic", "pyth", "beam", "ankr", "mask", "spell", "radiant", "frax", "ether.fi", "bitcoin dogs",
                "solv", "sign", "swell", "aurora", "kusama", "moonbeam", "liquity", "venus", "alchemy", "orca", "raydium", "sky",
                "tether", "usd coin", "dai", "pax gold", "tether gold", "first digital usd", "paypal usd", "chain", "virtual",
                "wrapped bitcoin", "lido staked ether", "official trump", "trump"}


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or ""); s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def item_id(source, title, link=""):
    return hashlib.sha1(f"{source}|{link or title}".encode()).hexdigest()[:16]


def _ms(datestr):
    try: return int(parsedate_to_datetime(datestr).timestamp() * 1000)
    except Exception: return None


def parse_rss(xml_text, source):
    out = []
    try: root = ET.fromstring(xml_text)
    except ET.ParseError: return out
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"): continue
        def g(*names):
            for n in names:
                e = next((c for c in it if c.tag.split("}")[-1] == n), None)
                if e is not None: return e          # (Element sem filhos é "falso": nunca usar `or`)
            return None
        t = g("title"); d = g("description", "summary"); p = g("pubDate", "published", "updated", "date"); l = g("link")
        title = strip_html(t.text if t is not None else "")
        if not title: continue
        link = (l.text or l.get("href") or "") if l is not None else ""
        pub = _ms(p.text) if p is not None and p.text else None
        if pub is None and p is not None and p.text:
            try:
                from datetime import datetime
                pub = int(datetime.fromisoformat(p.text.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception: pub = None
        out.append({"id": item_id(source, title, link.strip()), "source": source, "kind": "news", "title": title[:300],
                    "summary": strip_html(d.text if d is not None else "")[:400], "pub_ms": pub})
    return out


def parse_binance(json_text, source, kind):
    out = []
    try: j = json.loads(json_text)
    except ValueError: return out
    for c in ((j.get("data") or {}).get("catalogs") or []):
        for a in c.get("articles") or []:
            title = strip_html(a.get("title") or "")
            if not title: continue
            out.append({"id": item_id(source, title, str(a.get("code") or a.get("id"))), "source": source, "kind": kind,
                        "title": title[:300], "summary": "", "pub_ms": a.get("releaseDate")})
    return out


def parse_trending(json_text):
    try: j = json.loads(json_text)
    except ValueError: return []
    return sorted({str((c.get("item") or {}).get("symbol") or "").upper() for c in j.get("coins") or []} - {""})


def parse_markets(json_texts):
    """{nome_minúsculo: SÍMBOLO} a partir de coins/markets (o de maior market cap ganha em empates)."""
    m = {}
    for t in json_texts:
        try: rows = json.loads(t)
        except ValueError: continue
        for r in rows if isinstance(rows, list) else []:
            n, s = str(r.get("name") or "").strip().lower(), str(r.get("symbol") or "").upper()
            if n and s and n not in m: m[n] = s
    return m


def entities(text, universe, names):
    """Símbolos do universo mencionados no texto. universe: set de bases (ex. {'BTC','SOL'}); names: {nome: SYM}."""
    found = set()
    for m in re.finditer(r"\$([A-Z][A-Z0-9]{1,9})\b|\(([A-Z][A-Z0-9]{1,9})\)", text):
        s = m.group(1) or m.group(2)
        if s in universe: found.add(s)
    for m in re.finditer(r"(?<![\w$])([A-Z][A-Z0-9]{2,9})(?![\w])", text):
        s = m.group(1)
        if s in universe and s not in STOP_UPPER: found.add(s)
    low = text.lower()
    for n, s in list(ALIASES.items()) + list(names.items()):
        if s not in universe or n in COMMON_NAMES: continue
        if len(n) < 5 and n not in ALIASES: continue
        if re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", low): found.add(s)
    return sorted(found)


def sentiment(text):
    p = sorted(k for k, r in _POS.items() if r.search(text)); n = sorted(k for k, r in _NEG.items() if r.search(text))
    return max(-3, min(3, len(p) - len(n))), p, n


def score_item(it, universe, names, nlp):
    """Devolve {sym: score} + termos. Listagens Binance: (SYM) no título → +listing_bonus; deslistagem → delisting_score."""
    text = it["title"] + ". " + it.get("summary", "")
    coins = entities(text, universe, names)
    s, p, n = sentiment(text)
    if it["kind"] == "listing":
        listed = [x for x in re.findall(r"\(([A-Z0-9]{2,10})\)", it["title"]) if x in universe]
        is_list = bool(re.search(r"\b(will list|adds?|lists)\b", it["title"], re.I)) and not re.search(r"bstocks|futures|margin|perpetual|collateral", it["title"], re.I)
        coins = sorted(set(listed)) if is_list else []
        sc = {c: max(s, 0) + nlp["listing_bonus"] for c in coins}
    elif it["kind"] == "delisting":
        listed = [x for x in re.findall(r"\b([A-Z0-9]{2,10})\b", it["title"]) if x in universe and x not in STOP_UPPER]
        coins = sorted(set(listed)) if re.search(r"delist|removal", it["title"], re.I) and not re.search(r"margin|futures", it["title"], re.I) else []
        sc = {c: nlp["delisting_score"] for c in coins}
    else:
        sc = {c: s for c in coins}
    return {"coins": coins, "scores": sc, "pos_terms": p, "neg_terms": n, "sent": s}


# ---------------- rede (só GET públicos; nunca para a Revolut com chave) ----------------
def get_text(url, timeout=15):
    import requests
    try:
        r = requests.get(url, timeout=timeout, headers=UA, allow_redirects=True)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def fetch_all(due, spec_sources, get=get_text):
    """due: set de grupos a ler agora ('rss','listings','trending'). Devolve (itens, trending|None, erros)."""
    items, trending, errs = [], None, {}
    if "rss" in due:
        for name, url in spec_sources["rss"].items():
            t = get(url)
            if t is None: errs[name] = "falhou"; continue
            items += parse_rss(t, name)
    if "listings" in due:
        for name, url in spec_sources["listings"].items():
            t = get(url)
            if t is None: errs[name] = "falhou"; continue
            items += parse_binance(t, name, "delisting" if "delist" in name else "listing")
    if "trending" in due:
        t = get(spec_sources["trending"]["coingecko"])
        if t is None: errs["coingecko_trending"] = "falhou"
        else: trending = parse_trending(t)
    return items, trending, errs


def fetch_names(get=get_text):
    base = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page="
    txt = [t for t in (get(base + "1"), get(base + "2")) if t]
    return parse_markets(txt)
