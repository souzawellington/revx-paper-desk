"""python -m desk <comando>
  screener [--symbols BTC,ETH] | cartographer [--confirm] | risk_officer | gate | exit_clerk [--stage 4h|daily]
  auditor [--weekly] | kill | unkill | decide <alert_id> TAKEN|SKIPPED | close <pid> <price> | outbox [--pending] [--ack ID] | replay [...] | tournament"""
import json, sys


def main():
    if len(sys.argv) < 2: print(__doc__); return
    cmd, rest = sys.argv[1], sys.argv[2:]
    sys.argv = [f"desk {cmd}"] + rest
    if cmd == "decide":
        from .gate import decide
        if len(rest) != 2: raise SystemExit("uso: desk decide <alert_id> TAKEN|SKIPPED")
        decide(rest[0], rest[1]); return
    if cmd == "close":
        from .auditor import record_manual_close
        record_manual_close(rest[0], float(rest[1])); return
    if cmd == "outbox":
        from . import store
        if "--ack" in rest: store.ack(rest[rest.index("--ack") + 1]); return
        for a in store.outbox(pending_only="--pending" in rest): print(json.dumps(a, ensure_ascii=False))
        return
    if cmd == "kill":
        from .roles.guard import kill_path
        from . import store
        open(kill_path(), "w").write("killed at " + store.iso(store.now_ms()) + "\n")
        print("KILL armed:", kill_path()); return
    if cmd == "unkill":
        from .roles.guard import kill_path
        import os
        if os.path.exists(kill_path()): os.remove(kill_path())
        print("KILL cleared"); return
    mod = {"screener": "screener", "cartographer": "cartographer", "risk_officer": "risk_officer", "gate": "gate",
           "exit_clerk": "exit_clerk", "auditor": "auditor", "replay": "replay", "run": "run", "tournament": "tournament"}.get(cmd)
    if not mod: print(__doc__); raise SystemExit(1)
    import importlib
    importlib.import_module(f"desk.{mod}").main()


if __name__ == "__main__":
    main()
