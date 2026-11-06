import json, os, sys

for _k in ("REVX_API_KEY", "REVX_PRIVATE_KEY_PATH"): os.environ.pop(_k, None)   # nunca precisa de chaves


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv); cmd = a[0] if a else "status"
    from desk.scalp import spec as SP, run as R
    if cmd == "prereg":
        d = SP.freeze(); print(f"pré-registo congelado {d['frozen_at_utc']} sha256 {d['sha256']}")
    elif cmd == "replay":
        rep = R.replay(refresh="--cached" not in a)
        print(R.fmt_status({**R.status(), "replay": rep}))
    elif cmd == "run-once":
        print(json.dumps(R.Forward().run_once()))
    elif cmd == "loop":
        R.loop()
    elif cmd == "status":
        s = R.status(); print(json.dumps(s, indent=1, ensure_ascii=False, default=str) if "--json" in a else R.fmt_status(s))
    else:
        print(__doc__ or "uso: python -m desk.scalp prereg|replay|run-once|loop|status [--json]"); sys.exit(2)


if __name__ == "__main__":
    main()
