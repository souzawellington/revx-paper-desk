# 09 — BbandRsi (freqtrade-strategies/berlinguyinca, GPL-3.0; lógica re-implementada a partir da descrição)
Pré-registado 2026-10-19, parâmetros do original, sem tuning. 1H, long-only spot.
- Entrada: RSI(14, Wilder) < 30 E close < banda inferior Bollinger(20, 2σ) do preço típico; fill na abertura da vela seguinte.
- Saída: RSI > 70 (sai na abertura seguinte) | ROI +10% | stop −8% (adaptação obrigatória: o original usa −25%; o desk exige −8%).
- Stop e ROI no mesmo candle → stop. R = retorno líquido / 8%. Fees 0.09% + slippage 0.1% por lado.
