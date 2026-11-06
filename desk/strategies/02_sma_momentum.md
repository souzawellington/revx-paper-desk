# Strategy: SMA20>SMA50 momentum long
Spec: enter when close > SMA20 > SMA50 on 1H; stop = entry − 3×ATR(14); TP = +4R; exit also if close < SMA20. Fees as DESK_RULES.
Engine: `desk.tournament` momentum runner.
