"""uso: python -m desk.news prereg | run-once | loop | status [--json] | rebase <livro> --confirm   (PAPER ONLY)"""
import json, os, sys

for _k in ("REVX_API_KEY", "REVX_PRIVATE_KEY_PATH"): os.environ.pop(_k, None)   # nunca precisa de chaves


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv); cmd = a[0] if a else "status"
    from desk.news import spec as SP, run as R
    if cmd == "prereg":
        d = SP.freeze(); print(f"pré-registo congelado {d['frozen_at_utc']} sha256 {d['sha256']}")
    elif cmd == "run-once":
        print(json.dumps(R.Forward().run_once()))
    elif cmd == "loop":
        R.loop()
    elif cmd == "status":
        s = R.status(); print(json.dumps(s, indent=1, ensure_ascii=False, default=str) if "--json" in a else R.fmt_status(s))
    elif cmd == "rebase":
        if len(a) < 2: print(__doc__); sys.exit(2)
        nb = R.rebase(a[1], confirm="--confirm" in a); print(f"{a[1]}: rebase para ${nb['equity']} (ciclo {nb['cycles']})")
    else:
        print(__doc__); sys.exit(2)


if __name__ == "__main__":
    main()
