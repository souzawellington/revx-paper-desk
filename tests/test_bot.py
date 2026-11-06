import pytest
from bot.config import Config
from bot.sizing import full_kelly, size_position, expected_value, InsufficientData
from bot.risk import DrawdownMonitor, RiskMode, position_stop_hit
from bot.brokers import PaperBroker, Order
from bot.engine import Engine
from bot.sim import SyntheticMarket, NullSentiment, FixedStats
from bot.schema import validate


def cfg(tmp_path=None, **k):
    return Config(log_dir=str(tmp_path or "/tmp/botlogs"), **k)


def test_kelly_pdf_example():
    assert full_kelly(0.6, 1) == pytest.approx(0.20)


def test_quarter_and_cap():
    s = size_position(0.6, 1, 1, cfg())
    assert s.quarter_kelly == pytest.approx(0.05) and s.allocation == pytest.approx(0.05)
    s = size_position(0.9, 5, 1, cfg())  # f*=0.88 -> /4=0.22 -> cap 0.15
    assert s.allocation == pytest.approx(0.15)


def test_negative_edge_zero():
    assert size_position(0.3, 1, 1, cfg()).allocation == 0


def test_insufficient_data():
    with pytest.raises(InsufficientData):
        size_position(0.6, None, 1, cfg())


def test_only_quarter_kelly_allowed():
    with pytest.raises(ValueError):
        Config(kelly_fraction=0.5)
    with pytest.raises(ValueError):
        Config(max_position_fraction=0.2)


def test_ev():
    assert expected_value(0.6, 2, 1, 0.1) == pytest.approx(0.7)


def test_drawdown_modes():
    m = DrawdownMonitor(cfg())
    assert m.update(100) == RiskMode.NORMAL
    assert m.update(84) == RiskMode.REDUCE and m.risk_multiplier() == 0.5
    assert m.update(70) == RiskMode.SUSPEND
    assert m.update(100) == RiskMode.SUSPEND  # latched


def test_hard_stop_8pct_from_peak():
    c = cfg()
    assert position_stop_hit(100, 120, 110.3, None, c) == "HARD_STOP_8PCT"
    assert position_stop_hit(100, 100, 93, None, c) is None


def test_engine_buys_and_stops(tmp_path):
    c = cfg(tmp_path)
    mkt = SyntheticMarket(c.symbols); br = PaperBroker()
    e = Engine(c, br, mkt, NullSentiment(), FixedStats())
    d = e.cycle()
    buys = [x for x in d if x["action"] == "BUY"]
    assert buys and all(x["alloc"] <= 0.15 for x in buys)
    t = buys[0]["ticker"]; mkt.shock[t] = 0.85
    d2 = e.cycle()
    assert any(x["ticker"] == t and x["action"] == "SELL" for x in d2)


def test_engine_suspends_on_dd(tmp_path):
    c = cfg(tmp_path)
    mkt = SyntheticMarket(c.symbols); br = PaperBroker()
    e = Engine(c, br, mkt, NullSentiment(), FixedStats())
    e.cycle(); br._cash *= 0.3  # força DD de carteira
    e.cycle()
    assert e.cb.tripped and not br.positions()


def test_insufficient_samples(tmp_path):
    c = cfg(tmp_path)
    e = Engine(c, PaperBroker(), SyntheticMarket(c.symbols), NullSentiment(), FixedStats(n=5, wins=3))
    assert all("INSUFFICIENT_DATA" in x["reason"] for x in e.cycle())


def test_schema_rejects_over_15pct():
    d = {"market_intelligence": {"evaluation_timestamp_iso": "x", "asset_identification": "NVDA",
         "network_sentiment_polarity_score": 0, "technical_momentum_confidence": 0.5},
         "quantitative_reasoning_trace": {k: 0.1 for k in ["win_probability_p", "risk_reward_multiplier_b",
            "full_kelly_index_calculation", "fractional_kelly_quarter_enforced", "atr_multiplier_stop_distance"]},
         "execution_directive": {"action_type": "BUY", "order_structure": "MARKET", "limit_price_target": None,
            "stop_loss_trigger_price": 90, "capital_allocation_fraction": 0.2},
         "system_compliance_audit": {"drawdown_safeguard_status": "PASS", "analytical_rationale": "x"}}
    with pytest.raises(Exception):
        validate(d)
    d["execution_directive"]["capital_allocation_fraction"] = 0.1
    validate(d)
