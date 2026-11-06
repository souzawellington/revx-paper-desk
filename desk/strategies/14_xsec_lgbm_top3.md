# 14 — xsec_lgbm_top3 (ideia qlib Alpha158 + LightGBM, re-implementada) — pré-registada 2026-10-19
Ranking cross-sectional diário dos 15 pares; 50 features Alpha158-subset (z-score cross-sectional); label = retorno abertura t+1→t+2 rankeado.
LightGBM fixo (ver DESK_RULES, secção Pesquisa). Treino 2023-12→2025-04, validação 2025-04→2025-10 (early stop), teste = HOLDOUT 2025-10-20→2026-10-18.
Top-3 long-only, rebalance diário, 0.19%/lado, stop −8% diário; cada segmento contíguo detido = 1 trade, R = retorno/8%.
Mesmos limiares congelados + expectancy > 0 na Revolut X.
