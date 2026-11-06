"""Findings do Auditor (Texto 3 / QuantGPT adaptado). Labels EXACTOS:
DATA_VALIDATED | TRADE_OFF | NO_EDGE
Nunca sugere mudar limiares. IA nunca coloca ordens."""
from __future__ import annotations
from .rules import Rules


def label_finding(stats: dict, rules: Rules, oos: dict | None = None) -> str:
    """
    DATA_VALIDATED: full sample passa TODOS os limiares congelados E (se oos dado) OOS expectancy>0 e n_oos>=max(10, threshold/2).
    TRADE_OFF: trades>=threshold mas falha win_rate OU expectancy OU max_dd (há amostra, sem edge robusto).
    NO_EDGE: resto (amostra insuficiente ou expectancy claramente negativa).
    """
    th = stats.get("thresholds") or {}
    # stats() returns thresholds as {k: (value, pass_bool)}
    def passed(key):
        v = th.get(key)
        if isinstance(v, (list, tuple)) and len(v) == 2: return bool(v[1])
        return bool(v)
    n = stats.get("n", 0)
    go = stats.get("go", False)
    if go and (oos is None or (oos.get("n", 0) >= max(10, rules.threshold_trades // 2) and oos.get("expectancy_r", -1) > 0)):
        return "DATA_VALIDATED"
    if n >= rules.threshold_trades and not go:
        return "TRADE_OFF"
    return "NO_EDGE"


def format_finding_line(label: str) -> str:
    return f"Finding: **{label}** (labels congelados: DATA_VALIDATED | TRADE_OFF | NO_EDGE)."
