import json, time
import pytest
from bot.config import Config
from bot import backtest as bt
from bot.data import SignalStatsStore
from bot.sizing import InsufficientData
from bot.signals import technical_state


def mk(closes, start=0, iv=3_600_000, vol=1.0):
    return [{"start": start + i * iv, "open": c, "high": c * 1.005, "low": c * 0.995, "close": c, "volume": vol}
            for i, c in enumerate(closes)]


def test_no_lookahead_signal_uses_only_past():
    cfg = Config()
    c = mk([100 + i for i in range(60)])
    full = bt.simulate(c, cfg)
    # mudar o FUTURO não pode alterar a decisão de entrada no candle 51
    c2 = [dict(x) for x in c]
    for x in c2[53:]:
        x.update(open=1.0, high=1.0, low=1.0, close=1.0)
    s1 = technical_state(*[[x[k] for x in c[:52]] for k in ("high", "low", "close", "volume")], cfg)
    s2 = technical_state(*[[x[k] for x in c2[:52]] for k in ("high", "low", "close", "volume")], cfg)
    assert s1 == s2


def test_trade_r_multiples_and_hard_stop():
    cfg = Config()
    closes = [100 + i * 0.5 for i in range(60)] + [140, 150, 160, 160, 140]  # pico 160 -> -8% = 147.2
    c = mk(closes)
    trades = bt.simulate(c, cfg)
    assert trades
    t = trades[0]
    assert t.entry == c[52]["open"]                     # entrada na abertura seguinte ao sinal
    assert t.r_gross == pytest.approx((t.exit - t.entry) / t.entry / t.risk_frac)
    assert t.r_net < t.r_gross                          # custos aplicados
    assert any("STOP" in x.reason for x in trades)


def test_gap_exits_at_open():
    cfg = Config()
    closes = [100 + i * 0.5 for i in range(60)] + [50]
    trades = bt.simulate(mk(closes), cfg)
    assert trades[-1].reason.endswith("_GAP") and trades[-1].exit == 50


def test_stats_and_holdout():
    cfg = Config()
    s = bt.stats([bt.Trade(0, 1, 100, 110, 95, .05, 2.0, 1.9, "x", True),
                  bt.Trade(0, 1, 100, 95, 95, .05, -1.0, -1.1, "x", True)])
    assert s["n"] == 2 and s["p"] == .5 and s["avg_win"] == 2 and s["avg_loss"] == 1 and s["ev_r"] == .5


def test_fetch_pages_backwards_100_and_stops(tmp_path):
    cfg = Config()
    iv = 3_600_000; now = 1_000 * iv
    calls = []
    class C:
        def public_candles(self, sym, interval, since, until, region):
            calls.append((since, until)); assert (until - since) / iv == 100
            if since < 700 * iv: return []
            return [{"start": t, "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"}
                    for t in range(since, until + 1, iv)]  # inclui candle em formação
    rows = bt.fetch_history(C(), "BTC-USD", cfg, cache_dir=str(tmp_path), now_ms=now, log=lambda *a: None)
    assert len(rows) == 300 and rows[-1]["start"] + iv <= now   # candle em formação excluído
    assert len(calls) == 3 + 3                                   # 3 páginas com dados + 3 vazias


def _ledger(tmp_path, cfg, n=40, age=0.0):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"generated_at": time.time() - age * 86400, "config": bt.fingerprint(cfg),
                             "symbols": {"BTC-USD": {"n": n, "wins": n // 2, "avg_win": 2.0, "avg_loss": 1.0, "alpha": 0.3}}}))
    return str(p)


def test_store_ok(tmp_path):
    cfg = Config()
    h = SignalStatsStore(cfg, _ledger(tmp_path, cfg)).get("BTC-USD")
    assert h.n == 40 and h.alpha == 0.3


@pytest.mark.parametrize("kw,msg", [({"n": 10}, "n=10"), ({"age": 30}, "dias")])
def test_store_insufficient(tmp_path, kw, msg):
    cfg = Config()
    with pytest.raises(InsufficientData, match=msg):
        SignalStatsStore(cfg, _ledger(tmp_path, cfg, **kw)).get("BTC-USD")


def test_store_missing_and_config_mismatch(tmp_path):
    with pytest.raises(InsufficientData):
        SignalStatsStore(Config(), str(tmp_path / "x.json")).get("BTC-USD")
    p = _ledger(tmp_path, Config())
    with pytest.raises(InsufficientData, match="parâmetros"):
        SignalStatsStore(Config(atr_stop_multiplier=2.5), p).get("BTC-USD")
