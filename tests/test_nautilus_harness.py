"""Repo 4 — NautilusTrader (opcional, venv à parte). Exportador de intenções + smoke test do harness se o venv existir."""
import json, os, subprocess, sys
import pytest
from desk import intents
from desk.rules import load_rules
from tests.test_desk import path_hours
from tests.test_freqtrade_ideas import _h1

NVENV = "/workspace/.venv-nautilus/bin/python"


def _data(tmp_path, rows, sym="TST-USD"):
    d = tmp_path / "data"; d.mkdir(exist_ok=True); (d / f"candles_{sym}_60.json").write_text(json.dumps(rows)); return str(d)


def test_intents_from_replay_have_precommitted_stop_tp(tmp_path):
    from desk.rules import Rules
    d = _data(tmp_path, path_hours()); it = intents.from_replay(["TST-USD"], Rules({**load_rules().p, "no_hero": False}), d)
    assert it and all(i["stop_abs"] and i["tp_abs"] and i["tp_abs"] > i["stop_abs"] for i in it)
    assert all(i["trail_hard_pct"] == 0.08 for i in it)


def test_intents_from_community(tmp_path):
    d = _data(tmp_path, _h1(3000)); it = intents.build("09", ["TST-USD"], load_rules(), d)
    assert all(i["stop_pct"] == 0.08 and i["tp_pct"] == 0.10 for i in it)
    with pytest.raises(SystemExit): intents.build("99", ["TST-USD"], load_rules(), d)


def test_harness_has_no_live_adapters_or_credentials():
    src = open("tools/nautilus_harness.py").read()
    for bad in ("adapters", "TradingNode", "api_key", "apiKey", "secret", "LiveExecClient", "requests"):
        assert bad not in src


@pytest.mark.skipif(not os.path.exists(NVENV), reason="venv NautilusTrader opcional ausente")
def test_harness_matches_reference(tmp_path):
    d = _data(tmp_path, _h1(4000, seed=3)); it = intents.build("09", ["TST-USD"], load_rules(), d)
    f = tmp_path / "it.json"
    f.write_text(json.dumps({"spec": "09", "data_dir": d, "symbols": ["TST-USD"], "taker_fee": 0.0009, "slippage": 0.001, "intents": it}))
    out = subprocess.run([NVENV, "-W", "ignore", "-m", "tools.nautilus_harness", "--intents", str(f)], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    rep = json.loads(out.stdout)
    assert rep["nautilus_trades"] >= 0.9 * len(it) and rep["per_trade_abs_diff_r"]["median"] < 0.05
    assert rep["exit_type_agreement"] > 0.9
