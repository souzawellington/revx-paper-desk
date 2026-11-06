# 25 — desk FVG + teto HRP CVaR histórico 5% (Riskfolio-Lib, pré-registado 2026-10-19 antes de correr)
- Base: spec 01 sem alterações; overrides: alloc_mode: enforce, alloc_rm: CVaR.
- HRP (pearson, single linkage, bisecção recursiva) sobre retornos 1D fechados (90 dias comuns, mín. 30) do candidato + posições abertas.
- Teto do candidato = min(15%, w_HRP × N × 15%) do equity. Só reduz; sem posições abertas → sem efeito.
- R por trade não muda (preço); avaliam-se PnL, max DD, Ulcer, CVaR diário. Sem auto-promoção.
