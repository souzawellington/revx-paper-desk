"""Rotinas do desk.  python -m desk.run --stage daily|4h|1h|weekly
daily : screener -> cartographer -> exit_clerk(daily)
4h    : cartographer (refresh) -> exit_clerk(4h)
1h    : cartographer (confirm) -> risk_officer -> GUARD -> gate -> auditor.paper_fill + skipped_stats
weekly: auditor (relatório)
Dedupe: cada alerta tem id determinístico; store.emit ignora ids já presentes no outbox."""
from __future__ import annotations
import argparse, fcntl, os
from .rules import load_rules
from . import screener, cartographer, risk_officer, gate, exit_clerk, auditor, store
from .roles import guard


def stage(name, rules=None, client=None, now=None, symbols=None, log=print):
    rules = rules or load_rules()
    lock = open(store.path(".lock"), "w"); fcntl.flock(lock, fcntl.LOCK_EX)   # um estágio de cada vez
    try:
        if name == "daily":
            screener.run(rules, symbols, now, client, log); cartographer.run(False, rules, now, client, log)
            exit_clerk.run("daily", rules, now, client, log)
        elif name == "4h":
            cartographer.run(False, rules, now, client, log); exit_clerk.run("4h", rules, now, client, log)
        elif name == "1h":
            cartographer.run(True, rules, now, client, log); risk_officer.run(rules, now, log, client=client)
            guard.run(rules, now, log)
            gate.run(rules, now, client, log); auditor.paper_fill(rules, now, client, log)
            auditor.rebuild_skipped_stats(rules, log)
        elif name == "weekly":
            auditor.weekly(rules, now, log)
        else:
            raise SystemExit(f"estágio desconhecido {name}")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", required=True, choices=["daily", "4h", "1h", "weekly"])
    ap.add_argument("--symbols", help="limitar o screener (ex. BTC,ETH)"); a = ap.parse_args()
    rules = load_rules()
    syms = [f"{x.strip().upper()}-{rules.quote}" for x in a.symbols.split(",")] if a.symbols else None
    stage(a.stage, rules, symbols=syms)


if __name__ == "__main__":
    main()
