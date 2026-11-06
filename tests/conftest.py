import pytest


@pytest.fixture(autouse=True)
def _offline_xvenue(monkeypatch):
    """Testes nunca vão à rede para o sanity cross-venue (CCXT público)."""
    try:
        from desk import ccxt_data
    except Exception:
        return
    monkeypatch.setattr(ccxt_data, "live_sanity",
                        lambda coin, rx, venues=(), max_dev=0.02, ccxt_mod=None, log=print:
                        {"status": "INSUFFICIENT_DATA", "dev": None, "median": None, "venues": 0, "prices": {}})


@pytest.fixture(autouse=True)
def _offline_macro(monkeypatch):
    """Testes nunca vão à rede para o contexto macro (yfinance/OpenBB)."""
    try:
        from desk import macro
    except Exception:
        return
    def _no_net(*a, **k): raise ConnectionError("offline nos testes")
    monkeypatch.setattr(macro, "fetch", _no_net)
