import json, logging, os, time


def setup(log_dir: str) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    lg = logging.getLogger("bot")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        h = logging.FileHandler(os.path.join(log_dir, "bot.log"))
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h); lg.addHandler(logging.StreamHandler())
    return lg


def audit(log_dir: str, record: dict):
    """Matriz de rastreabilidade (PDF): JSONL append-only com carimbo temporal."""
    os.makedirs(log_dir, exist_ok=True)
    record = {"ts": time.time(), **record}
    with open(os.path.join(log_dir, "audit.jsonl"), "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
