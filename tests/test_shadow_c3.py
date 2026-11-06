"""Bot-sombra C3 (NÃO VALIDADA): paper-only, idempotente, isolado do auditor/executor. Rede simulada (sem chamadas reais)."""
import json, os
import numpy as np
import pytest
from desk import store
from desk.shadow import c3 as C

D, H = C.D, C.H
T0 = 1_780_000_000_000 // D * D


def series(n=200, drift=0.004, seed=0):
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(drift, 0.02, n))))


class Net:
    """Fake HTTP: velas Revolut X (dia de Londres = UTC−1h) / Coinbase (UTC) e livro com spread fixo."""
    def __init__(self, closes, revx_up=True, cb_up=True, lows=None):
        self.c = closes; self.revx_up = revx_up; self.cb_up = cb_up; self.lows = lows or {}; self.calls = []

    def rows(self, s, now):
        out = []
        for i, c in enumerate(self.c[s]):
            st = T0 + i * D
            if st > now: break
            o = self.c[s][i - 1] if i else c
            out.append((st, o, max(o, c), self.lows.get(s, {}).get(i, min(o, c)), c))
        return out

    def __call__(self, url, params=None, **k):
        self.calls.append(url); now = self.now
        s = "BTC" if "/BTC-" in url else "ETH"
        if "revx" in url:
            if not self.revx_up: return None
            if "candles" in url:
                return {"data": [{"start": st - H, "open": str(o), "high": str(h), "low": str(l), "close": str(c), "volume": "1"}
                                 for st, o, h, l, c in self.rows(s, now)]}
            last = self.rows(s, now)[-1][4]
            return {"data": {"bids": [{"p": str(last * 0.999)}], "asks": [{"p": str(last * 1.001)}]}}
        if not self.cb_up: return None
        if "candles" in url: return [[st // 1000, l, h, o, c, 1] for st, o, h, l, c in reversed(self.rows(s, now))]
        last = self.rows(s, now)[-1][4]
        return {"bids": [[str(last * 0.999), "1", 1]], "asks": [[str(last * 1.001), "1", 1]]}


def day_now(i): return T0 + i * D + 2 * H          # vela i em curso; i−1 é a última fechada


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE", str(tmp_path)); monkeypatch.delenv("C3_STATE_DIR", raising=False)
    return tmp_path


def run(net, i, **k):
    net.now = day_now(i); return C.run_once(now_ms=net.now, get=net, **k)


def test_weights_match_research_engine():
    from desk.research import estudo as E
    cl = {"BTC": series(300, seed=1), "ETH": series(300, drift=-0.003, seed=2)}
    P = {"ts": T0 + np.arange(300) * D, "syms": ["BTC", "ETH"], "close": np.array([cl["BTC"], cl["ETH"]]).T}
    W, _ = E.s_trend(P, None, ["BTC", "ETH"], 100, 1); Wc = E.desk_caps(W)
    for t in (150, 220, 299):
        raw = C.target_weights({s: cl[s][:t + 1] for s in cl}, caps=False); cap = C.target_weights({s: cl[s][:t + 1] for s in cl}, caps=True)
        for j, s in enumerate(("BTC", "ETH")):
            assert raw[s]["w"] == pytest.approx(W[t, j], abs=1e-12) and cap[s]["w"] == pytest.approx(Wc[t, j], abs=1e-12)
    assert C.target_weights({"BTC": [1.0] * 50, "ETH": [1.0] * 50}, True)["BTC"]["why"] == "INSUFFICIENT_DATA"


def test_first_run_enters_emits_simulado_and_is_idempotent(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)})
    r = run(net, 150)
    assert r["status"] == "PROCESSED" and r["source"] == "revx"
    books = {(t["book"], t["coin"]) for t in r["trades"]}
    assert {("c3", "BTC"), ("c3", "ETH"), ("c3_raw", "BTC"), ("c3_raw", "ETH"), ("bh_btc", "BTC")} <= books
    st = r["state"]
    for k in ("c3", "c3_raw", "bh_btc"): assert st["books"][k]["equity"] < 65.5
    expo = 1 - st["books"]["c3"]["cash"] / st["books"]["c3"]["equity"]
    assert 0.2 < expo <= 0.2501                                  # 2 × 12,5% (tetos do desk)
    buy = next(t for t in r["trades"] if t["book"] == "c3" and t["coin"] == "BTC")
    assert float(buy["price"]) == pytest.approx(net.c["BTC"][150] * 1.001, rel=1e-6)   # ao ASK do livro ao vivo
    ob = store.outbox(); assert len(ob) == 1
    a = ob[0]
    assert a["type"] == "SHADOW_C3_TRADE" and a["autonomous"] and a["reply_options"] == [] and a["tag"] == "c3_unvalidated"
    assert "SIMULADO" in a["text"] and "NÃO VALIDADA" in a["text"]
    n_tr = len(C._read("trades.csv"))
    r2 = run(net, 150); r3 = C.run_once(now_ms=day_now(150) + 5 * H, get=net)
    assert r2["status"] == r3["status"] == "ALREADY_PROCESSED"
    assert len(C._read("trades.csv")) == n_tr and len(C._read("equity.csv")) == 1 and len(store.outbox()) == 1


def test_never_feeds_auditor_or_executor(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    for f in ("journal.csv", "positions.csv", "trade_plan.csv", "decisions.csv"):
        assert not os.path.exists(os.path.join(env, f))
    assert os.path.exists(os.path.join(env, "shadow_c3", "state.json"))
    assert all(r["tag"] == "c3_unvalidated" for r in C._read("trades.csv"))
    assert all(a["type"].startswith("SHADOW_C3_") for a in store.outbox())


def test_quiet_when_nothing_changes(env):
    btc = [100.0 * 1.003 ** i for i in range(200)]; net = Net({"BTC": btc, "ETH": list(btc)})
    run(net, 150); n = len(store.outbox())
    r = run(net, 151)
    assert r["status"] == "PROCESSED" and not [t for t in r["trades"] if t["book"] != "bh_btc"] and len(store.outbox()) == n


def test_stop_8pct_blocks_reentry_and_notifies(env):
    up = [100.0 * 1.003 ** i for i in range(152)]
    net = Net({"BTC": up + [up[-1] * 0.90] * 48, "ETH": [100.0 * 1.003 ** i for i in range(200)]})
    run(net, 151)                              # processa vela 150 (alta) → entra ao preço ao vivo da vela 151
    n = len(store.outbox())
    r = run(net, 153)                          # vela 152 a −10% ⇒ stop −8%; sinal continua ON ⇒ reentrada bloqueada
    sells = [t for t in r["trades"] if t["book"] == "c3" and t["coin"] == "BTC"]
    assert sells and sells[0]["side"] == "SELL" and sells[0]["reason"].startswith("STOP_8PCT")
    assert r["state"]["books"]["c3"]["units"]["BTC"] == 0 and r["state"]["books"]["c3"]["blocked"]["BTC"]
    assert len(store.outbox()) == n + 1 and store.outbox()[-1]["type"] == "SHADOW_C3_TRADE"


def test_signal_exit_without_stop(env):
    up = [100.0 * 1.003 ** i for i in range(151)]
    btc = up + [up[-1] * 0.99] * 49                 # cai 1%: sem stop; SMA100 ainda abaixo → mantém
    net = Net({"BTC": btc, "ETH": list(up) + [up[-1]] * 49}); run(net, 151)
    btc2 = up + [up[-1] * 0.95, up[-1] * 0.94] + [up[-1] * 0.94] * 47
    net.c["BTC"] = btc2; net.c["BTC"][152] = 50.0; net.lows = {"BTC": {152: 49.0}}
    r = run(net, 153)
    assert any(t["book"] == "c3_raw" and t["coin"] == "BTC" and t["side"] == "SELL" for t in r["trades"])


def test_coinbase_fallback_then_data_gap_pause(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    net.revx_up = False
    r = run(net, 151); assert r["source"] == "coinbase" and r["status"] == "PROCESSED" and "_global" not in r["flags"]
    r = run(net, 152); assert "_global" not in r["flags"]
    r = run(net, 153)
    assert r["flags"].get("_global", "").startswith("DATA_GAP_REVX") and r["state"]["paused"]
    assert any(a["type"] == "SHADOW_C3_PAUSE" for a in store.outbox())
    n = len(C._read("trades.csv")); r = run(net, 154)
    assert not [t for t in r["trades"] if t["book"] != "bh_btc"] and len(C._read("trades.csv")) == n   # pausado: não negoceia
    C.resume("_global"); assert C.load_state()["paused"] is None


def test_no_data_anywhere_is_safe(env):
    net = Net({"BTC": series(200), "ETH": series(200)}, revx_up=False, cb_up=False)
    r = run(net, 150); assert r["status"] == "NO_DATA" and not store.outbox()


def test_drawdown_pause_flag(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    st = C.load_state(); st["books"]["c3_raw"]["peak"] = 100.0; C.save_state(st)
    r = run(net, 151)
    assert r["flags"].get("c3_raw", "").startswith("FORWARD_DD>20%") and r["state"]["books"]["c3_raw"]["paused"]
    assert "c3" not in r["flags"]


def test_status_cli(env, capsys):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    C.main(["status"]); out = json.loads(capsys.readouterr().out)
    assert out["tag"] == "c3_unvalidated" and set(out["books"]) == {"c3", "c3_raw", "bh_btc"}


def test_paper_only_isolation():
    src = open(C.__file__).read()
    import ast
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import): mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom): mods.add(n.module or "")
    assert not [m for m in mods if m.split(".")[0] in ("live", "bot")] and "desk.rules" not in mods
    for bad in ("REVX_API_KEY", "private.pem", "execution_mode: live", "requests.post", "requests.delete", "os.environ[\"REVX"):
        assert bad not in src
    assert C.BROKER is None; C._assert_paper_only()
    C.BROKER = object()
    try:
        with pytest.raises(RuntimeError): C._assert_paper_only()
    finally:
        C.BROKER = None
    lines = [l.strip() for l in open("desk/DESK_RULES.md") if l.strip().startswith("execution_mode:")]
    assert lines and all(l != "execution_mode: live" for l in lines)


def test_replica_runs_on_same_candles():
    cl = {s: series(220, seed=i) for i, s in enumerate(("BTC", "ETH"))}
    cs = {s: [{"start": T0 + i * D, "open": (v[i - 1] if i else v[i]), "high": max(v[i], v[i - 1] if i else v[i]),
               "low": min(v[i], v[i - 1] if i else v[i]), "close": v[i]} for i in range(220)] for s, v in cl.items()}
    rep = C.replica_equity(cs, T0 + 150 * D, caps=True)
    assert len(rep) == 69 and rep[0][1] > 0


# ---------------- teto 1000 / reset 65 / critérios de morte ----------------
def test_ceiling_1000_pauses_c3_books_bh_only_flags_and_rebase_to_65(env):
    from desk import health as HL
    assert HL.ceiling(env={}) == 1000 and HL.reset_balance() == 65
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    st = C.load_state()
    for k in st["books"]: st["books"][k]["cash"] += 2000.0       # equity simulada > 1000
    C.save_state(st)
    r = run(net, 151)
    b = r["state"]["books"]
    assert b["c3"]["paused"]["reason"].startswith("CEILING") and b["c3_raw"]["paused"]["reason"].startswith("CEILING")
    assert b["bh_btc"].get("paused") is None and b["bh_btc"]["ceiling"]               # baseline: só aviso
    ob = [a for a in store.outbox() if a["type"] == "SHADOW_C3_CEILING"]
    assert len(ob) == 3 and all("teto atingido, sacar e deixar o saldo inicial" in a["text"] and "SIMULADO" in a["text"] for a in ob)
    n = len(C._read("trades.csv")); r = run(net, 152)
    assert not [t for t in r["trades"] if t["book"] != "bh_btc"]                      # pausado no teto
    with pytest.raises(SystemExit): C.main(["rebase", "c3"])                          # exige --confirm
    C.main(["rebase", "all", "--confirm"])
    st = C.load_state()
    for k in ("c3", "c3_raw", "bh_btc"):
        assert st["books"][k]["cash"] == 65 and st["books"][k]["peak"] == 65 and not st["books"][k].get("paused")
    r = run(net, 153)
    assert any(t["book"] == "bh_btc" and t["reason"] == "BASELINE_BUY" for t in r["trades"])  # baseline recompra
    assert r["state"]["books"]["bh_btc"]["equity"] == pytest.approx(65, rel=0.01)


def test_bh_btc_drawdown_is_informational_only(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    st = C.load_state(); st["books"]["bh_btc"]["peak"] = 100.0; C.save_state(st)
    r = run(net, 151)
    assert "bh_btc" not in r["flags"] and not r["state"]["books"]["bh_btc"].get("paused")
    assert any(a["type"] == "SHADOW_C3_INFO" for a in store.outbox())
    km = r["state"]["kill_metrics"]
    assert km["bh_btc"]["forward_dd"]["tripped"] and km["bh_btc"]["forward_dd"]["informational"]
    assert set(km["c3"]) >= {"forward_dd", "sharpe_12m", "divergence", "data_gap_revx"}
    assert km["c3"]["forward_dd"]["limit"] == "> 14%" and km["c3_raw"]["forward_dd"]["limit"] == "> 20%"


def test_no_data_for_days_pauses_global_with_api_criterion(env):
    net = Net({"BTC": series(200), "ETH": series(200, seed=3)}); run(net, 150)
    net.revx_up = net.cb_up = False
    r = run(net, 151); assert r["status"] == "NO_DATA" and not r["flags"]            # 1 dia: não dispara
    r = run(net, 152); assert not r["flags"]
    r = run(net, 153)                                                               # 3 falhas seguidas, ≥ 48 h
    assert r["flags"]["_global"] and C.load_state()["paused"]
    assert any(a["type"] == "SHADOW_C3_PAUSE" for a in store.outbox())
