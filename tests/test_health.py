"""desk.health: relatório só-leitura (sem rede) com todos os bots, teto e critérios."""
import json
from desk import store, health as HL


def test_health_report_reads_states_without_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "STATE", str(tmp_path)); monkeypatch.delenv("C3_STATE_DIR", raising=False)
    monkeypatch.delenv("BOT_TARGET_BALANCE", raising=False)
    rep = HL.report(now=1_800_000_000_000)
    assert rep["ceiling"] == 1000 and rep["reset_balance"] == 65
    assert {"A_c3", "A_c3_raw", "B_bh_btc"} <= set(rep["bots"])
    assert rep["bots"]["A_c3"]["ceiling_distance"] == 1000 - 65
    assert "api_errors" in rep["bots"]["A_c3"]["criteria"] and "data_stale" in rep["bots"]["A_c3"]["criteria"]
    if rep["execution_mode"] in ("paper_autonomous", "live"):
        assert "D_executor" in rep["bots"]
    HL.main([]); assert "ceiling $1,000" in capsys.readouterr().out
    HL.main(["--json"]); assert json.loads(capsys.readouterr().out)["ceiling"] == 1000
