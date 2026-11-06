"""Estado partilhado do desk: CSVs em desk/state (todos os papéis leem e escrevem aqui)."""
from __future__ import annotations
import csv, json, os, time
from datetime import datetime, timezone

STATE = os.environ.get("DESK_STATE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")

SCHEMAS = {
    "watchlist.csv": ["coin", "anchor_low", "flip_date", "tag"],
    "context.csv": ["ts", "coin", "event", "flip_date", "note"],
    "zones.csv": ["coin", "zone_id", "rank", "zone_top", "zone_bottom", "status", "confirmed", "formed_ts", "tested_ts",
                  "test_low", "entry", "stop", "confirm_ts", "last_h1", "last_h4", "anchor_low"],
    "trade_plan.csv": ["plan_id", "coin", "zone_id", "entry", "stop", "tp_price", "size", "notional", "risk_pct", "add_number",
                       "anchor_low", "created_ts", "equity", "equity_source", "sizing_binding", "panel", "prot", "macro", "alloc", "tag"],
    "plan_rejections.csv": ["ts", "coin", "zone_id", "reason"],
    "decisions.csv": ["ts", "alert_id", "plan_id", "decision"],
    "positions.csv": ["pid", "plan_id", "coin", "status", "entry", "stop", "initial_stop", "tp_price", "qty", "risk_pct", "add_number",
                      "anchor_low", "opened_ts", "peak", "at_be", "stale_flagged", "last_h1", "last_d1", "exit", "exit_ts", "exit_rule", "tag"],
    "journal.csv": ["ts", "trade_id", "coin", "line", "price", "qty", "amount_usd", "r", "mode", "decision", "note", "tag"],
}


def path(name): os.makedirs(STATE, exist_ok=True); return os.path.join(STATE, name)


def read(name) -> list[dict]:
    p = path(name)
    if not os.path.exists(p): return []
    with open(p, newline="") as f: return list(csv.DictReader(f))


def write(name, rows: list[dict]):
    cols = SCHEMAS[name]; p = path(name); tmp = p + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in cols})
    os.replace(tmp, p)


def append(name, rows: list[dict]):
    if not rows: return
    cols = SCHEMAS[name]; p = path(name); new = not os.path.exists(p)
    if not new:   # migração: cabeçalho antigo (ex. sem coluna nova) -> reescreve com o schema actual
        with open(p, newline="") as fh: hdr = next(csv.reader(fh), [])
        if hdr != cols: write(name, read(name))
    with open(p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new: w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in cols})


def f(x, d=None):
    try: return float(x)
    except (TypeError, ValueError): return d


def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ms not in (None, "", -1) else ""


def now_ms(): return int(time.time() * 1000)


# ---------- outbox (append-only, com dedupe por id) ----------
def outbox_ids() -> set:
    p = path("outbox.jsonl")
    if not os.path.exists(p): return set()
    return {json.loads(l)["id"] for l in open(p) if l.strip()}


def emit(alert: dict) -> bool:
    """Acrescenta ao outbox se o id ainda não existir. Devolve True se emitido."""
    if alert["id"] in outbox_ids(): return False
    alert = {"status": "PENDING", "created_at": iso(now_ms()), **alert}
    with open(path("outbox.jsonl"), "a") as fh: fh.write(json.dumps(alert, default=str) + "\n")
    return True


def outbox(pending_only=False) -> list[dict]:
    p = path("outbox.jsonl")
    if not os.path.exists(p): return []
    acks = set()
    pa = path("outbox_acks.jsonl")
    if os.path.exists(pa): acks = {json.loads(l)["id"] for l in open(pa) if l.strip()}
    out = []
    for l in open(p):
        if not l.strip(): continue
        a = json.loads(l); a["status"] = "RELAYED" if a["id"] in acks else a.get("status", "PENDING")
        if not pending_only or a["status"] == "PENDING": out.append(a)
    return out


def ack(alert_id):
    with open(path("outbox_acks.jsonl"), "a") as fh: fh.write(json.dumps({"id": alert_id, "ts": iso(now_ms())}) + "\n")
