"""PaperBroker tpsl: a hora da colocação (e a hora corrente) é coberta por velas 1m; preços ANTES da colocação não contam.
Caso real 2026-10-22: METIS tocou 3.81 às 11:07Z, a compra encheu às 11:11:45Z, o stop 3.816 nunca foi tocado depois."""
import pytest
from live.brokers import PaperBroker

H, M = 3_600_000, 60_000
T0 = 1_800_000_000_000 // H * H
SYM = "TST-USD"


class Mkt:
    def __init__(self): self.h1, self.m1 = [], []
    def ticker(self, s): return {"bid": 100.0, "ask": 100.0, "mid": 100.0, "last_price": 100.0}
    def pairs(self): return {}
    def candles(self, s, interval, since, until=None):
        if interval == 1:
            return [c for c in self.m1 if c["start"] >= since // M * M and (until is None or c["start"] < until)]
        return [c for c in self.h1 if c["start"] >= since // H * H]


def bar(start, o, h, l, c): return {"start": start, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def broker(tmp_path, placed):
    m = Mkt(); b = PaperBroker(str(tmp_path / "px.json"), m, cash=0.0, clock=lambda: placed)
    b.s["bal"]["TST"] = 1.0
    oid = b.tpsl_sell(SYM, "1", "120", "95", "c1")["id"]
    return m, b, b.s["orders"][oid]


def test_stop_hit_in_placement_hour_is_caught(tmp_path):
    placed = T0 + 10 * M + 30_000
    m, b, o = broker(tmp_path, placed)
    m.m1 = [bar(T0 + 11 * M, 99, 99, 96, 96), bar(T0 + 40 * M, 96, 96, 94.5, 95.5)]
    m.h1 = [bar(T0, 99, 100, 94.5, 98), bar(T0 + H, 98, 99, 97, 98)]     # depois recupera
    b.advance(T0 + H + 6 * M)
    assert o["status"] == "filled" and o["trigger_reason"] == "stop_loss"
    assert o["avg"] == pytest.approx(95 * (1 - b.slip))


def test_pre_placement_print_below_stop_is_ignored(tmp_path):
    """METIS: o mínimo da vela 1H da colocação foi ANTES do fill; não pode disparar o stop."""
    placed = T0 + 11 * M + 45_000
    m, b, o = broker(tmp_path, placed)
    m.m1 = [bar(T0 + 7 * M, 94.9, 94.9, 94.9, 94.9), bar(T0 + 12 * M, 99, 99, 95.2, 95.2), bar(T0 + 30 * M, 96, 98, 96, 98)]
    m.h1 = [bar(T0, 99, 101, 94.9, 98), bar(T0 + H, 98, 100, 96, 99)]
    b.advance(T0 + 2 * H + 6 * M)
    assert o["status"] == "new" and o["checked_to"] == T0 + 2 * H


def test_stop_hit_in_current_hour_before_hour_close(tmp_path):
    placed = T0 + 5 * M
    m, b, o = broker(tmp_path, placed)
    m.h1 = [bar(T0 + H, 99, 100, 97, 98)]
    m.m1 = [bar(T0 + 2 * H + 3 * M, 97, 97, 94, 94.5)]
    b.advance(T0 + 2 * H + 10 * M)                  # vela 1H T0+2H ainda aberta
    assert o["status"] == "filled" and o["trigger_reason"] == "stop_loss"


def test_no_minute_data_falls_back_to_old_behaviour(tmp_path):
    placed = T0 + 10 * M
    m, b, o = broker(tmp_path, placed)
    m.h1 = [bar(T0, 99, 100, 94, 98), bar(T0 + H, 98, 100, 96, 99)]   # sem 1m: a hora da colocação é saltada como antes
    b.advance(T0 + 2 * H + 6 * M)
    assert o["status"] == "new" and o["checked_to"] == T0 + 2 * H
    m.h1.append(bar(T0 + 2 * H, 98, 99, 94, 95))
    b.advance(T0 + 3 * H + 6 * M)
    assert o["status"] == "filled" and o["trigger_reason"] == "stop_loss"
