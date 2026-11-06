"""Snapshot público (página Vercel): sanitizador + teste que FALHA se aparecerem campos/valores com cara de segredo."""
import json, os, subprocess
import pytest
from bot import public_snapshot as PS
from bot import live_view as LV
from tests.test_dashboard_live import FakePub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEAKY = {
    "simulated": True, "bots": [{"key": "A_c3", "equity": 65.1, "api_key": "abc", "REVX_API_KEY": "zzz",
                                 "note": "-----BEGIN PRIVATE KEY-----\nMC4CAQ...", "pem_path": "/home/box/.revx-keys/private.pem"}],
    "password": "hunter2", "ingest_token": "t", "env": {"X": 1}, "Authorization": "Basic d2VsbDpwdw==",
    "msg": "erro em /home/box/.revx-keys/private.pem", "blob": "A" * 40, "hex": "a" * 40, "envline": "REVX_API_KEY=abcdef",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig", "hdr": "Bearer abcdefghijklmnop",
    "fine": {"coin": "BTC-USD", "price": 82000.5, "ts": "20/10 16:48", "reason": "ENTER", "name": "Bot A · C3 com teto 12,5%"},
}


def test_sanitizer_removes_every_secret_looking_thing():
    out = PS.sanitize(LEAKY)
    blob = json.dumps(out)
    for bad in ("api_key", "REVX", "BEGIN", "private.pem", "hunter2", "password", "token", "Authorization", ".revx-keys", "pem_path",
                "A" * 40, "a" * 40, "eyJ", "Bearer"):
        assert bad not in blob, bad
    assert out["fine"] == LEAKY["fine"]
    assert out["bots"][0]["equity"] == 65.1 and out["bots"][0]["key"] == "A_c3"
    PS.assert_clean(out, secrets=[])


@pytest.mark.parametrize("bad", [
    {"api_key": "x"}, {"x": {"private_key": 1}}, {"password": "p"}, {"token": "t"}, {"key_path": "k"}, {"env": {}},
    {"m": "-----BEGIN PRIVATE KEY-----"}, {"m": "/home/box/.revx-keys/private.pem"}, {"m": "~/.revx-keys"},
    {"m": "Z" * 48}, {"m": "REVX_API_KEY=abc"}, {"m": "Basic d2VsbGluZ3Rvbjpwdw=="},
])
def test_assert_clean_fails_on_secret_looking_fields(bad):
    with pytest.raises(PS.SecretLeak):
        PS.assert_clean(bad, secrets=[])


def test_assert_clean_fails_on_known_secret_value():
    with pytest.raises(PS.SecretLeak):
        PS.assert_clean({"m": "x my-very-secret-pw y"}, secrets=["my-very-secret-pw"])


def test_known_secrets_reads_env_and_files(tmp_path):
    (tmp_path / ".vercel_dashboard_password").write_text("filepw-123456\n")
    s = PS.known_secrets(env={"REVX_API_KEY": "envkey-123456"}, root=str(tmp_path))
    assert "envkey-123456" in s and "filepw-123456" in s


def test_real_snapshot_is_clean_and_simulated(monkeypatch, tmp_path):
    monkeypatch.setenv("REVX_API_KEY", "fake-revx-key-should-never-appear-123")
    snap = PS.build(prices=LV.Prices(FakePub(), None), marks=PS._ReadOnlyMarks(str(tmp_path / "none.jsonl")))
    assert snap["simulated"] is True and snap["live_orders"] is False and snap["schema"] == 1
    assert "SIMULADO" in snap["banner"] and isinstance(snap["generated_at"], int)
    keys = {b["key"] for b in snap["bots"]}
    assert {"D_executor", "A_c3", "A_c3_raw", "B_bh_btc"} <= keys and all(k.startswith("S_") for k in keys - {"D_executor", "A_c3", "A_c3_raw", "B_bh_btc"})
    for b in snap["bots"]:
        if b["key"].startswith("S_"): assert "SIMULADO" in b["name"] and b["paper"] is True
    blob = json.dumps(snap)
    assert "fake-revx-key-should-never-appear-123" not in blob
    for s in PS.known_secrets():
        assert s not in blob
    for b in snap["bots"]:
        assert len(b.get("curve") or []) <= PS.MAX_CURVE
    assert len(blob) < 512 * 1024
    PS.assert_clean(snap)


def test_snapshot_with_error_path_is_scrubbed(monkeypatch, tmp_path):
    snap = PS.build(prices=LV.Prices(FakePub(fail=True), None), marks=PS._ReadOnlyMarks(str(tmp_path / "none.jsonl")))
    assert "/home/box" not in json.dumps(snap)


def test_build_refuses_if_leak_survives(monkeypatch, tmp_path):
    import bot.live_view as lv
    real = lv.live_snapshot
    monkeypatch.setattr(lv, "live_snapshot", lambda *a, **k: {**real(*a, **k), "note": "leak: s3cr3t-value-xyz"})
    monkeypatch.setattr(PS, "known_secrets", lambda *a, **k: ["s3cr3t-value-xyz"])
    with pytest.raises(PS.SecretLeak):
        PS.build(prices=LV.Prices(FakePub(), None), marks=PS._ReadOnlyMarks(str(tmp_path / "none.jsonl")))


def test_secret_files_are_private_and_ignored():
    gi = open(os.path.join(ROOT, ".gitignore")).read()
    for f in (".vercel_dashboard_password", ".vercel_ingest_token", ".dashboard_password"):
        assert f in gi
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            assert (os.stat(p).st_mode & 0o077) == 0, f"{f} deve ser chmod 600"


def test_push_script_dry_run_never_sends_and_never_echoes_token(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("REVX_")}
    env.update({"VERCEL_DASH_URL": "https://invalid.invalid", "VERCEL_INGEST_TOKEN_FILE": str(tmp_path / "tok")})
    (tmp_path / "tok").write_text("tok-should-not-print-0123456789abcdef")
    r = subprocess.run([os.path.join(ROOT, "tools", "push_snapshot.sh"), "--dry-run"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "dry-run OK" in r.stdout and "tok-should-not-print" not in r.stdout + r.stderr


def test_push_script_has_no_trading_or_key_access():
    src = open(os.path.join(ROOT, "tools", "push_snapshot.sh")).read()
    assert "-u REVX_API_KEY" in src and "private.pem" not in src
    for bad in ("execution_mode", "live.executor", "unkill", "rebase", "place_order", "DESK_RULES"):
        assert bad not in src
    psrc = open(os.path.join(ROOT, "bot", "public_snapshot.py")).read()
    for bad in ("place_order", "load_private_key", "execution_mode =", "open(pem"):
        assert bad not in psrc
