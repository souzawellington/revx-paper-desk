"""Lê DESK_RULES.md (bloco ```params```) — fonte única de verdade de todos os papéis."""
from __future__ import annotations
import os, re
from dataclasses import dataclass

DESK_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(DESK_DIR, "DESK_RULES.md")


def _cast(v: str):
    v = v.strip()
    if v.lower() in ("true", "false"): return v.lower() == "true"
    try: return int(v)
    except ValueError: pass
    try: return float(v)
    except ValueError: return v


def parse_params(text: str) -> dict:
    m = re.search(r"```params\s*\n(.*?)```", text, re.S)
    if not m: raise ValueError("DESK_RULES.md sem bloco ```params```")
    out = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line: continue
        k, v = line.split(":", 1)
        out[k.strip()] = _cast(v)
    return out


REQUIRED = ["quote", "risk_pct", "add_risk_pct", "max_position_frac", "hard_stop_pct", "stale_hours", "threshold_trades",
            "threshold_win_rate", "threshold_expectancy_r", "threshold_max_dd", "taker_fee", "slippage", "paper_equity",
            "take_profit_r", "no_hero", "max_leverage_equivalent", "max_open_positions", "max_total_risk_pct", "daily_loss_halt_pct"]


@dataclass(frozen=True)
class Rules:
    p: dict
    def __getattr__(self, k):
        try: return self.p[k]
        except KeyError: raise AttributeError(k)
    @property
    def exclude(self): return {x.strip().upper() for x in str(self.p.get("exclude_bases", "")).split(",") if x.strip()}


def load_rules(path: str = RULES_PATH) -> Rules:
    p = parse_params(open(path, encoding="utf-8").read())
    miss = [k for k in REQUIRED if k not in p]
    if miss: raise ValueError(f"DESK_RULES.md: parâmetros em falta {miss}")
    if p["hard_stop_pct"] != 0.08: raise ValueError("hard-stop −8% é obrigatório (PDF do bot)")
    if p["max_position_frac"] > 0.15: raise ValueError("teto 15% (PDF do bot)")
    if float(p["risk_pct"]) > 0.01: raise ValueError("risk_pct trancado ≤ 1% (Texto 1 / no-hero)")
    if float(p["max_leverage_equivalent"]) != 1: raise ValueError("Revolut X = spot: max_leverage_equivalent deve ser 1")
    if float(p["take_profit_r"]) <= 0: raise ValueError("take_profit_r > 0")
    if str(p.get("execution_mode", "off")) not in ("off", "paper_autonomous", "live"):
        raise ValueError("execution_mode tem de ser off | paper_autonomous | live")
    if float(p.get("exec_dd_suspend", 0.30)) > 0.30 or float(p.get("exec_dd_reduce", 0.15)) > 0.15:
        raise ValueError("DD reduce ≤ 15% e suspend ≤ 30% (trancados)")
    if float(p.get("kill_dd_max", 0.20)) > 0.20: raise ValueError("kill_dd_max ≤ 20% (critério de morte do utilizador)")
    if float(p.get("target_balance", 0) or 0) > 0 and not 0 < float(p.get("reset_balance", 65)) < float(p["target_balance"]):
        raise ValueError("reset_balance tem de ser > 0 e < target_balance")
    pf = {k: v for k, v in p.items() if k.startswith("paper_") and k not in PAPER_FAST_KEYS + ("paper_equity", "paper_autonomous_equity")}
    if pf: raise ValueError(f"parâmetros paper_* desconhecidos {sorted(pf)} (só {PAPER_FAST_KEYS})")
    if int(p.get("paper_max_open_positions", p["max_open_positions"])) > PAPER_MAX_OPEN_LIMIT:
        raise ValueError(f"paper_max_open_positions ≤ {PAPER_MAX_OPEN_LIMIT}")
    if float(p.get("paper_max_total_risk_pct", p["max_total_risk_pct"])) > \
            float(p.get("paper_max_open_positions", p["max_open_positions"])) * float(p["risk_pct"]) + 1e-12:
        raise ValueError("paper_max_total_risk_pct ≤ paper_max_open_positions × risk_pct")
    if not 0 <= float(p.get("paper_entry_tol", 0.01)) <= 0.02: raise ValueError("paper_entry_tol entre 0 e 2%")
    if str(p.get("paper_entry_mode", "post_only")) not in ("post_only", "marketable"):
        raise ValueError("paper_entry_mode tem de ser post_only | marketable")
    return Rules(p)


# ---- ensaio acelerado (paper_fast): SÓ com execution_mode == paper_autonomous; NUNCA afecta live/off ----
PAPER_FAST_KEYS = ("paper_fast", "paper_max_open_positions", "paper_max_total_risk_pct", "paper_entry_mode", "paper_entry_tol")
PAPER_MAX_OPEN_LIMIT = 10
PAPER_FAST_TAG = "paper_fast"
_OVERRIDES = {"max_open_positions": "paper_max_open_positions", "max_total_risk_pct": "paper_max_total_risk_pct"}


def paper_fast_active(rules) -> bool:
    return str(rules.p.get("execution_mode", "off")) == "paper_autonomous" and bool(rules.p.get("paper_fast", False))


def eff(rules, key):
    """Valor efectivo de max_open_positions / max_total_risk_pct: override paper_* só no ensaio paper_fast."""
    pk = _OVERRIDES.get(key)
    if pk and paper_fast_active(rules) and pk in rules.p: return rules.p[pk]
    return rules.p[key]


def run_tag(rules) -> str:
    return PAPER_FAST_TAG if paper_fast_active(rules) else ""
