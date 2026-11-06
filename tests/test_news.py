"""Livros NEWS (paper only, news_v1): extração de moedas, léxico, anti-topo, custos, enchimentos sem look-ahead, kill/teto,
rebase manual, baseline_on_start, notícias velhas, ciclo forward offline completo, painel sem segredos, sem chaves/broker."""
import inspect, json, os
from decimal import Decimal
import pytest

from desk.news import engine as E, spec as SP, run as R, sources as S
from desk.news.engine import Engine, new_state, to_json, from_json, M1, D, BOOKS, TRAINING, HALTED, CEILING

T0 = 1793150400000            # 2026-10-28T00:00Z
UNI = {"BTC", "ETH", "SOL", "XRP", "PEPE", "INJ", "QNT", "AERO"}
NAMES = {"bitcoin": "BTC", "solana": "SOL", "injective": "INJ", "pepe": "PEPE", "aerodrome finance": "AERO", "quant": "QNT"}


def feat(**k):
    f = {"news_score": 2, "vol_ratio": 3.0, "mom_15m": 0.01, "runup": 0.01, "chg_24h": 0.03, "atr_pct": 0.006, "close": 100.0, "news_ids": ["a"]}
    f.update(k); return f


# ---------------- spec / isolamento ----------------
def test_spec_frozen_and_rules():
    R_ = SP.SPEC["risk"]
    assert SP.SPEC["id"] == "news_v1" and R_["start_equity"] == "65" and R_["dd_kill"] == "0.20" and R_["ceiling"] == "1000"
    assert R_["risk_pct"] == "0.01" and R_["pos_cap_frac"] == "0.33" and R_["max_open"] == 3
    assert SP.SPEC["execution"]["taker_fee"] == "0.0009" and SP.SPEC["execution"]["maker_fee"] == "0" and SP.SPEC["execution"]["slippage"] == "0.0010"
    assert set(BOOKS) == {"news_momo", "news_pullback"}


def test_prereg_matches_repo_freeze():
    assert os.path.exists(SP.PREREG), "pré-registo tem de existir antes do primeiro trade"
    doc = json.load(open(SP.PREREG)); assert doc["sha256"] == SP.spec_hash() == SP.check()


def test_no_broker_no_keys_no_live():
    assert E.BROKER is None
    for mod in (E, R, S):
        src = inspect.getsource(mod)
        for bad in ("REVX_API_KEY", "private.pem", "execution_mode", "place_order", "sign(", "live/"):
            assert bad not in src, (mod.__name__, bad)


# ---------------- NLP ----------------
def test_entities_cashtags_upper_and_names():
    assert S.entities("Solana and $PEPE rally; INJ listed", UNI, NAMES) == ["INJ", "PEPE", "SOL"]
    assert S.entities("SEC sues ETF issuer, CEO says", UNI | {"SEC"}, NAMES) == []          # stoplist
    assert S.entities("Quant fund buys stocks", UNI, NAMES) == []                           # nome comum
    assert S.entities("Ripple wins approval", UNI, NAMES) == ["XRP"]                        # alias


def test_sentiment_lexicon():
    s, p, n = S.sentiment("Bitcoin ETF inflows climb as BTC rebounds"); assert s == 3 and not n
    s, p, n = S.sentiment("Exchange hacked, funds drained"); assert s <= -2
    assert S.sentiment("Bitcoin drops while tech rallies")[0] == 0


def test_listing_and_delisting_scores():
    nlp = SP.SPEC["nlp"]
    it = {"kind": "listing", "title": "Binance Will List Aerodrome (AERO) with Seed Tag Applied", "summary": ""}
    assert S.score_item(it, UNI, NAMES, nlp)["scores"] == {"AERO": 3}       # +1 léxico ("will list") +2 bónus
    it = {"kind": "listing", "title": "Binance Futures Will Launch USDⓈ-Margined PEPE (PEPE) Perpetual", "summary": ""}
    assert S.score_item(it, UNI, NAMES, nlp)["scores"] == {}
    it = {"kind": "delisting", "title": "Binance Will Delist QNT, INJ on 2026-11-05", "summary": ""}
    assert S.score_item(it, UNI, NAMES, nlp)["scores"] == {"INJ": -3, "QNT": -3}


def test_parse_rss_dates_and_summary():
    x = ("<rss><channel><item><title>Solana surges</title><description>&lt;p&gt;SOL up&lt;/p&gt;</description>"
         "<pubDate>Wed, 28 Oct 2026 07:57:18 +0000</pubDate><link>https://x.example/a</link></item></channel></rss>")
    it = S.parse_rss(x, "t")[0]
    assert it["title"] == "Solana surges" and it["summary"] == "SOL up" and it["pub_ms"] == 1793174238000


# ---------------- filtros / custos ----------------
def test_anti_top_filters():
    assert "anti-topo" in E.filters("news_momo", feat(runup=0.031))
    assert "anti-topo" in E.filters("news_momo", feat(chg_24h=0.13))
    assert "subiu demais" in E.filters("news_momo", feat(mom_15m=0.031))
    assert "volume" in E.filters("news_momo", feat(vol_ratio=1.9))
    assert E.filters("news_pullback", feat(vol_ratio=1.6, runup=0.045)) is None
    assert E.filters("news_momo", feat(news_score=0)) == "sem notícia positiva"
    assert E.filters("news_momo", feat()) is None


def test_reject_when_target_does_not_cover_costs():
    st = new_state(0); eng = Engine(st)
    ok, why = eng.evaluate("news_momo", "PEPE-USD", feat(atr_pct=0.001), T0, 0.004)   # d=0,8% → alvo 1,6% − custo 1,18% < 0,5%
    assert not ok and "custos" in why and st["books"]["news_momo"]["n"]["rej_cost"] == 1


def test_macro_risk_off_and_cooldown_and_busy():
    st = new_state(0); eng = Engine(st)
    assert eng.evaluate("news_momo", "BTC-USD", feat(), T0, 0.0001, "RISK_OFF") == (False, "macro RISK_OFF")
    assert eng.evaluate("news_momo", "BTC-USD", feat(), T0, 0.0001)[0]
    assert "cooldown" in eng.evaluate("news_momo", "BTC-USD", feat(), T0 + M1, 0.0001)[1]
    for s in ("ETH-USD", "SOL-USD"): assert eng.evaluate("news_momo", s, feat(), T0, 0.0001)[0]
    assert "ocupado" in eng.evaluate("news_momo", "XRP-USD", feat(), T0, 0.0001)[1]


def test_risk_sizing_and_cap():
    st = new_state(0); eng = Engine(st)
    assert eng.evaluate("news_momo", "BTC-USD", feat(atr_pct=0.01), T0, 0.0001)[0]
    q = st["books"]["news_momo"]["pend"]["BTC-USD"]
    assert q["d"] == D("0.02") and q["qty"] * D("100") * (1 + D("0.0011")) <= D("65") * D("0.33")
    assert st["books"]["news_momo"]["cash"] == D("65") - q["reserve"]


# ---------------- enchimentos ----------------
def test_taker_fills_next_minute_open_with_costs():
    st = new_state(0); tr = []; eng = Engine(st, on_trade=tr.append)
    now = T0 + 30_000
    assert eng.evaluate("news_momo", "BTC-USD", feat(atr_pct=0.01), now, D("0.0005"))[0]
    eng.bar("BTC-USD", T0, 100, 120, 90, 100, D("0.0005"))            # vela da decisão: nunca enche (sem look-ahead)
    assert "BTC-USD" in st["books"]["news_momo"]["pend"]
    eng.bar("BTC-USD", T0 + M1, 101, 101.5, 100.5, 101, D("0.0005"))
    p = st["books"]["news_momo"]["pos"]["BTC-USD"]
    assert p["entry"] == D("101") * (1 + D("0.001") + D("0.0005")) and p["entry_fee"] == p["qty"] * p["entry"] * D("0.0009")


def test_maker_fills_only_when_low_crosses_limit():
    st = new_state(0); eng = Engine(st)
    assert eng.evaluate("news_pullback", "SOL-USD", feat(atr_pct=0.01), T0, D("0.0005"))[0]
    q = st["books"]["news_pullback"]["pend"]["SOL-USD"]; L = q["limit"]
    assert L == D("100") * (1 - D("0.02") * D("0.5"))
    eng.bar("SOL-USD", T0 + M1, 100, 100, float(L), 100)               # toca mas não atravessa
    assert "SOL-USD" in st["books"]["news_pullback"]["pend"]
    eng.bar("SOL-USD", T0 + 2 * M1, 100, 100, float(L) - 0.01, 99.5)
    assert st["books"]["news_pullback"]["pos"]["SOL-USD"]["entry"] == L and st["books"]["news_pullback"]["pos"]["SOL-USD"]["entry_fee"] == 0


def test_pending_maker_expires_and_refunds():
    st = new_state(0); eng = Engine(st)
    eng.evaluate("news_pullback", "SOL-USD", feat(atr_pct=0.01), T0, D("0.0005"))
    for i in range(1, 33): eng.bar("SOL-USD", T0 + i * M1, 100, 100, 100, 100)
    b = st["books"]["news_pullback"]; assert not b["pend"] and b["cash"] == D("65") and b["n"]["unfilled"] == 1


def _filled(book="news_momo"):
    st = new_state(0); tr = []; eng = Engine(st, on_trade=tr.append)
    eng.evaluate(book, "BTC-USD", feat(atr_pct=0.01), T0, D("0.0005"))
    eng.bar("BTC-USD", T0 + M1, 100, 100, 100, 100, D("0.0005"))
    return st, eng, tr, st["books"][book]["pos"].get("BTC-USD")


def test_stop_beats_target_same_bar_and_costs():
    st, eng, tr, p = _filled()
    eng.bar("BTC-USD", T0 + 2 * M1, 100, 200, 50, 100, D("0.0005"))
    assert tr[0]["reason"] == "stop" and -1.01 < tr[0]["r"] < -0.99 and tr[0]["fee"] > 0


def test_target_maker_and_time_stop():
    st, eng, tr, p = _filled()
    eng.bar("BTC-USD", T0 + 2 * M1, 100, float(p["tp"]) + 0.01, 99.9, 100)
    assert tr[0]["reason"] == "alvo (maker)" and tr[0]["r"] > Decimal("1.5")
    st, eng, tr, p = _filled()
    for i in range(2, 245): eng.bar("BTC-USD", T0 + i * M1, 100, 100, 100, 100)
    assert tr and tr[0]["reason"].startswith("tempo")


def test_dd_kill_halts_and_ceiling_pauses_and_rebase_needs_confirm(tmp_path, monkeypatch):
    st = new_state(0); ev = []; eng = Engine(st, on_event=ev.append)
    st["books"]["news_momo"]["cash"] = D("51"); eng.mark(T0)
    assert st["books"]["news_momo"]["state"] == HALTED and ev[0]["type"] == HALTED
    st["books"]["news_pullback"]["cash"] = D("1000"); eng.mark(T0)
    assert st["books"]["news_pullback"]["state"] == CEILING
    assert not eng.evaluate("news_momo", "BTC-USD", feat(), T0, 0.0001)[0]
    monkeypatch.setenv("NEWS_STATE_DIR", str(tmp_path))
    R._atomic_json(os.path.join(R.fdir(), "state.json"), to_json(st))
    with pytest.raises(SystemExit): R.rebase("news_pullback")
    nb = R.rebase("news_pullback", confirm=True); assert nb["equity"] == D("65") and nb["cycles"] == 1


def test_decimal_roundtrip():
    st, eng, tr, p = _filled(); assert from_json(json.loads(json.dumps(to_json(st)))) == st


# ---------------- forward offline ----------------
RSS0 = ("<rss><channel><item><title>Old Bitcoin story surges</title><pubDate>Wed, 28 Oct 2026 06:00:00 +0000</pubDate>"
        "<link>https://x.example/old</link></item></channel></rss>")


def rss_new(ts_ms, title):
    from email.utils import format_datetime
    from datetime import datetime, timezone
    d = format_datetime(datetime.fromtimestamp(ts_ms / 1000, timezone.utc))
    return f"<rss><channel><item><title>{title}</title><pubDate>{d}</pubDate><link>https://x.example/{ts_ms}</link></item></channel></rss>"


class Fake:
    def __init__(self, now): self.now = now; self.rss = RSS0; self.calls = []
    def clock(self): return self.now
    def get_text(self, url):
        if "coingecko" in url and "markets" in url: return json.dumps([{"name": "Solana", "symbol": "sol"}])
        if "trending" in url: return json.dumps({"coins": [{"item": {"symbol": "SOL"}}]})
        if "binance" in url: return json.dumps({"data": {"catalogs": [{"articles": []}]}})
        return self.rss if "cointelegraph" in url else None
    def get(self, url, params=None):
        self.calls.append(url)
        if url.endswith("/public/tickers"):
            return {"data": [{"symbol": "SOL/USD", "region": "UK", "bid": "99.99", "ask": "100.01", "mid": "100", "quote_volume_24h": "500000"},
                             {"symbol": "USDT/USD", "region": "UK", "bid": "1", "ask": "1.0001", "mid": "1", "quote_volume_24h": "900000"}]}
        if "/public/candles/" in url:
            iv = params["interval"]; a, b = params["since"], params["until"]; out = []
            t = (a // (iv * M1)) * iv * M1
            while t <= b:
                if t + iv * M1 <= self.now:
                    late = t >= self.now - 20 * M1
                    c = 100.0 + (0.4 if late and iv == 5 else 0.0)
                    out.append({"start": t, "open": str(c - 0.05), "high": str(c + 0.05), "low": str(c - 0.3), "close": str(c),
                                "volume": "50" if late else "5"})
                t += iv * M1
            return {"data": out}
        return None


@pytest.fixture
def prereg_ok(monkeypatch):
    monkeypatch.setattr(SP, "check", lambda path=None: SP.spec_hash())


def test_forward_baseline_then_live_news_trades_and_logs(tmp_path, monkeypatch, prereg_ok):
    monkeypatch.setenv("NEWS_STATE_DIR", str(tmp_path))
    now = T0 + 9 * 3_600_000; fk = Fake(now)
    fw = R.Forward(get=fk.get, get_text=fk.get_text, clock=fk.clock, log=lambda *a: None, macro=lambda ts: "OK")
    r = fw.run_once(); assert r["ok"], r
    items = R._tail_jsonl(os.path.join(R.fdir(), "news_items.jsonl"), 10)
    assert items and items[0]["decision"].startswith("baseline_on_start")
    fk.now += 4 * M1; fk.rss = rss_new(fk.now - 10 * M1, "Solana surges as ETF inflows climb")
    for g in fw.meta["polled"]: fw.meta["polled"][g] = 0
    r = fw.run_once(); assert r["ok"], r
    sig = R._tail_jsonl(os.path.join(R.fdir(), "signals.jsonl"), 5)[-1]
    assert sig["coin"] == "SOL" and sig["trending"] and sig["news_score"] >= 2 and sig["vol_ratio"] > 2
    assert any(v.startswith("ACEITE") for v in sig["books"].values()), sig
    st = from_json(json.load(open(os.path.join(R.fdir(), "state.json"))))
    assert "SOL-USD" in st["books"]["news_momo"]["pend"]
    fk.now += 3 * M1; r = fw.run_once(); assert r["ok"]
    st = from_json(json.load(open(os.path.join(R.fdir(), "state.json"))))
    assert "SOL-USD" in st["books"]["news_momo"]["pos"]
    # status() counts the last 24h of wall-clock time. The fixture clock is 2026-10-28,
    # so pin time.time to that clock or the window slides off the sample.
    monkeypatch.setattr(R.time, "time", lambda: fk.now / 1000)
    s = R.status(); assert s["forward"]["accepted_24h"] >= 1 and "NEWS books" in R.fmt_status(s)


def test_stale_news_never_trades(tmp_path, monkeypatch, prereg_ok):
    monkeypatch.setenv("NEWS_STATE_DIR", str(tmp_path))
    now = T0 + 9 * 3_600_000; fk = Fake(now)
    fw = R.Forward(get=fk.get, get_text=fk.get_text, clock=fk.clock, log=lambda *a: None, macro=lambda ts: "OK")
    fw.run_once(); fk.now += 4 * M1; fk.rss = rss_new(fk.now - 120 * M1, "Solana surges")
    for g in fw.meta["polled"]: fw.meta["polled"][g] = 0
    fw.run_once()
    last = R._tail_jsonl(os.path.join(R.fdir(), "news_items.jsonl"), 1)[0]
    assert last["decision"].startswith("ignorada: velha") and not fw.meta["active"]


def test_dashboard_data_clean(tmp_path, monkeypatch, prereg_ok):
    monkeypatch.setenv("NEWS_STATE_DIR", str(tmp_path))
    test_forward_baseline_then_live_news_trades_and_logs(tmp_path, monkeypatch, None)
    from bot.public_snapshot import sanitize, assert_clean
    d = R.dashboard_data(); assert d["available"] and d["cards"] and d["signals"]
    clean = sanitize(d); assert assert_clean(clean, secrets=[])
    assert clean["cards"][0]["id"] == d["cards"][0]["id"] and len(clean["signals"]) == len(d["signals"])
    assert all("http" not in json.dumps(n) for n in d["news"])
