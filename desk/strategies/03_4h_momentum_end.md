# Strategy: 4H trend + momentum-end exit
Spec: enter on 4H close > SMA20>SMA50; exit when 4H close < SMA20 (momentum end) OR stop −2×ATR OR TP +4R. Fees as DESK_RULES.
Engine: `desk.tournament` h4 runner.
