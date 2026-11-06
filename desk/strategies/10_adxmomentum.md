# 10 — ADXMomentum (freqtrade-strategies/berlinguyinca, GPL-3.0; lógica re-implementada a partir da descrição)
Pré-registado 2026-10-19, parâmetros do original, sem tuning. 1H, long-only spot.
- Entrada: ADX(14) > 25 E MOM(14) > 0 E +DI(25) > 25 E +DI > −DI; fill na abertura seguinte.
- Saída: ADX > 25 E MOM < 0 E −DI > 25 E +DI < −DI (abertura seguinte) | ROI +1% | stop −8% (original −25%).
- Stop e ROI no mesmo candle → stop. R = retorno líquido / 8%. Fees 0.09% + slippage 0.1% por lado.
