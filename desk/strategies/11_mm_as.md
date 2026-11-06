# 11_mm_as — MM Avellaneda-style (skew de inventário)
Pré-registado 2026-10-19 (antes de correr). Simulação apenas (`python -m desk.mm_sim`), nunca alerta de execução.
- Dados: fita pública de trades Revolut X, 14 dias, BTC/ETH/SOL/DOGE-USD (`data_tape/`).
- Holdout: 60% dias in-sample (ajuste de κ) / 40% OOS.
- Cotação a cada 300 s: mid = mediana dos últimos 20 trades; σ de retornos de 1 min (1 h); h = (max(2 bps, 1/κ) + 0.5σ) × 1.
- r = mid·(1 − q·h); bid = r(1−h) se q < 0.6; ask = r(1+h) ≤ inventário. Ordem $20, capital $65, ≤ 576 ordens/dia.
- Fills: latência 2 s, só trades do agressor oposto estritamente através, 50% da quantidade. Maker 0%; saídas forçadas taker 0.09% + 0.1%.
- Veredicto: limiares congelados (≥40 round trips, WR ≥33%, ≥ +0.4R com R = PnL/(notional×8%), DD ≤20%) + OOS > 0.
