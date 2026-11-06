# Lacunas: versão cripto

As lacunas 1–16 da versão de ações continuam válidas (ver `../revolut-bot/GAPS.md`). Resumo: o PDF não define o limite de drawdown da carteira (usado REDUCE 15% / SUSPEND 30%), trata os −8% como exemplo, e não define α, a amostra mínima para p, o desconto do sentimento, o proxy de volume, o sinal de momentum nem os parâmetros xAI.

## Novas lacunas e adaptações para cripto
1. **O PDF é sobre ações.** Ele menciona a Revolut X só como canal de encenação de ordens. Aplicar as mesmas regras a cripto é uma extrapolação.
2. **Volatilidade mais alta: defaults ajustados.**
   - Stop ATR a 3× (ações: 2×).
   - Candles de 60 min, 100 candles por janela.
   - Dados considerados obsoletos acima de 2 h.
   - Slippage estimado de 0,1% por lado.
   - O −8% e o teto de 15% ficam como no PDF. Com cripto, o −8% vai disparar com muito mais frequência. Pode ser preciso calibrar, mas o PDF não autoriza mudar o valor.
3. **Drawdown de carteira 15%/30%.** A faixa do PDF é de ações. Em cripto, quedas de 30% podem acontecer em poucos dias, então SUSPEND tende a ser acionado com frequência. A trava exige reset manual.
4. **Custo C.** Usado `2×(taker 0,09% + slippage)`, assumindo ordens a mercado na entrada e na saída. Maker = 0%, mas ordens limit/post-only não são usadas na entrada. Taxas de levantamento e de rede são ignoradas.
5. **Proxy de volume.** Volume do candle mais recente fechado ÷ SMA20. O volume da Revolut X reflete só a liquidez dessa bolsa, não o mercado global.
6. **Entrada e pico não vêm da API.** `/balances` não devolve preço médio. O bot grava a entrada e o pico em `logs/revx_positions.json` e **ignora posições que não abriu**. Uma alternativa seria reconstruir via `/orders/historical` ou `/trades/private`, que não foi implementada.
7. **Stops avaliados só a cada ciclo.** O stop não fica no servidor da exchange. A API documenta ordens condicionais/TPSL, mas o formato não foi verificado e não foi implementado. Entre ciclos, o risco de gap não é coberto.
8. **Ordens market não são reconciliadas.** O bot não consulta `GET /orders/{id}` nem `/orders/fills/{id}` para confirmar o preço médio. A entrada usa o preço de referência (mid).
9. **Sincronização de relógio.** A API rejeita timestamps no futuro (409). Use NTP. Não há ajuste automático.
10. **Staking.** O saldo `staked` é excluído da posição negociável. O equity usa `total`.
11. **Região.** Os tickers públicos podem trazer o mesmo par em várias regiões (UK, EEA). Sem `BOT_REGION`, usa-se a primeira entrada.
12. **Limites de candles.** A doc diz `(until−since)/interval ≤ 100` em `/candles` e um apêndice cita 50000. Foram usados 100.
13. **Venda a descoberto.** Não existe no spot: o bot é long-only, e SELL só fecha posições.
14. **O universo BTC/ETH/SOL é escolha própria.** O PDF cita ações (NVDA, TSLA…).
15. **Sub-contas.** O limite de 1000 ordens/dia não se aplica a sub-contas. O cliente aplica o limite sempre, por ser mais conservador.

## Backtest (adicionado em 2026-10-14)
16. **Histórico curto.** Os candles públicos de 60 min só existem desde 2025-10-09, cerca de 1 ano (8 897 candles). Pedidos mais antigos voltam vazios. É só um regime de mercado.
17. **Amostra pequena.** Saem 39–58 trades por símbolo no total e 9–20 fora da amostra, o que dá n<30 em todos. O bot fica em INSUFFICIENT_DATA. Mesmo com n=30, o intervalo de confiança de p é de cerca de ±15 pp.
18. **p baixo e b alto.** As saídas são só por stop (o bot ao vivo não tem take-profit nem saída por perda do sinal), então o resultado depende de poucos trades muito vencedores. A estimativa de b é instável.
19. **alpha.** A fórmula `1 − EV_oos/EV_is` só se aplica quando EV_is > 0. Na execução real, EV_is foi negativo e EV_oos positivo para os três símbolos, então alpha=0. Isso indica dependência de regime, não "ausência de sobreajuste". As regras não foram otimizadas; o holdout serve só para não estimar p sobre os mesmos dados que o validam.
20. **Diferenças em relação ao live.**
    - O backtest entra na abertura do candle seguinte; o live entra no mid do momento do ciclo.
    - O backtest assume que o stop executa no próprio nível dentro do candle, ou na abertura quando há gap. Na prática o slippage nos stops tende a ser pior.
    - Uma posição por símbolo, sem reforços. Os trades ainda abertos no fim dos dados são excluídos.
21. **Custos.** p, avg_win e avg_loss são publicados em R bruto, porque o engine já subtrai C no EV. A Kelly f* ignora custos. O R líquido fica no ledger (`net_out_of_sample`, `mean_r_net`).
22. **Volume confirmado.** Afeta apenas o ajuste de sentimento no live, não a entrada, por isso não condiciona os trades do backtest.
23. **Período de validade do ledger (7 dias) e holdout de 40%.** Escolhas próprias.

## Dashboard e variantes (2026-10-14)
24. Saldos em moedas fora do universo (ex.: XRP, ADA) aparecem com valor "–" e ficam fora do equity calculado.
25. Variantes: o TP é avaliado depois do stop no mesmo candle (conservador). As entradas maker assumem fill na abertura com 0% de taxa e sem slippage, o que é otimista: na prática há risco de não executar e de seleção adversa. Nenhuma variante tem n OOS ≥ 30 com IS positivo; ver o relatório.

## Desk "Trade Grok Bot" (2026-10-19)
O PDF do desk é para perpétuos USDT short-only. Foi espelhado para spot long-only; ver `desk/DESK_RULES.md`.
26. **"Closes up/down" no C1.** Interpretado como close > open (vela verde). Um doji também é aceite como C1, porque a regra diz "dojis são válidos" sem dizer para que vela.
27. **Âncora.** Ficou C1.low, o mínimo do impulso (C2 e C3 não o tocam por regra). O PDF não define a validade do flip: aqui vale até um fecho 1D abaixo da âncora, com lookback de 10 dias e expiração da watchlist aos 30 dias (escolhas próprias).
28. **"4H pulling back" (PRIME)** não está definido no PDF. Definido como: última vela 4H fecha abaixo da abertura e abaixo do fecho anterior.
29. **Confirmação 1H** não está definida no PDF ("Confirmation: 1H"). Definida como:
    - depois do teste, a primeira vela 1H com close > open e close > zone_top, sem fecho abaixo de zone_bottom;
    - entrada = esse fecho; stop = pavio mínimo desde o teste, limitado a −8%;
    - zona INVALID quando há fecho 4H (ou 1H durante o teste) abaixo de zone_bottom.
30. **Stop do plano** não está no PDF (que só tem a saída pela âncora 1D). Sem ele não se calcula tamanho por risco. Também se aplica sempre o hard-stop de −8% do PDF do bot.
31. **"Breakeven"** não está definido. Definido como: o preço atingiu entrada + 1R, e a partir daí o stop da entrada sobe para a entrada (`be_move_stop`). Sensibilidade com `be_move_stop=false`: ver o relatório.
32. **NEUTRAL** não está definido. Interpretado como sem flip ativo, nem de alta nem de baixa. A regra "em lucro → manter" fica implícita: não há saída por NEUTRAL.
33. **Flat 72h** não está definido. Definido como posição aberta há ≥72h com |close/entrada − 1| < 1%. Em paper a posição mantém-se: o PDF diz "o humano decide".
34. **Fills em paper.** Entrada na abertura da vela 1H seguinte ao alerta, com taker 0,09% + slippage 0,1% por lado. A saída usa o nível do stop, ou a abertura em caso de gap. É otimista para altcoins pouco líquidas.
35. **Quarter-Kelly do ledger** só existe para BTC/ETH/SOL e com n<30, por isso não está disponível (o tamanho fica pelo risco ou pelo teto de 15%). No replay nunca é usado (seria look-ahead).
36. **Stops curtos e teto de 15%.** Com stops curtos, o teto de 15% limita o tamanho e o risco efetivo fica abaixo de 1%. Isso infla o R de trades isolados (até +97R): a expectancy em R é dominada por outliers. O relatório mostra também a mediana, a expectancy sem o melhor trade e o PnL por risco planeado.
37. **Sem limite de risco agregado entre moedas** (o PDF não o define).
38. **Telegram** substituído pelo outbox. O agente reencaminha os alertas.
39. **Replay limitado** aos pares com histórico 1H em cache (cerca de 1 ano). O universo real tem ~300 pares, o que gera viés de seleção (pares grandes).

## Texto 1 (Loofyb0i) — 2026-10-19
40. Take-profit pré-comprometido a `take_profit_r` (default 4). No mesmo candle stop+TP → STOP (conservador).
41. `no_hero`: só PRIME+CONFIRMED; planos que ultrapassariam tetos → `CAP_EXCEEDED` em plan_rejections.
42. `max_leverage_equivalent: 1` tranca spot (sem alavancagem). Trading real continua desactivado.
43. Após TAKEN, só o stop pode subir a BE; `tp_price`/`initial_tp` são immutáveis.

## Texts 2–5 (2026-10-19)
44. Cost gate uses `threshold_win_rate` as planning win_p (break-even p without costs would always yield EV≤0 after fees).
45. GUARD counts unfilled trade_plans toward max_open / total risk (slots reserved).
46. SKIPPED downrank requires n≥skipped_downrank_min_n and expectancy≤skipped_downrank_max_ev.
47. Tournament momentum max_dd is an R-equity heuristic; use expectancy/win_rate for ranking. No strategy auto-promoted.
48. Kill switch does not place exchange orders for TAKEN — only EXIT NOW alert + paper close.

## Repo 1 — ai-hedge-fund (2026-10-19)
49. Janelas dos analistas adaptadas a cripto 24/7 (momentum 7/21/42 dias em vez de 21/63/126 dias úteis; vol anualizada com 365). Escolhas próprias, fixadas antes do replay.
50. `btc_regime_1d` é novo (não existe no repo): substitui o "mercado" para cripto. Quando BTC não está no replay/cache, o analista abstém-se.
51. Neutro → ×0.5 é escolha própria (no repo o PM decide via LLM). Reduzir tamanho não muda o R por trade; só PnL e drawdown.
52. Painel sem dados (falha de rede ou histórico curto) → sem efeito e regista INSUFFICIENT_DATA; não bloqueia o alerta, porque as regras do desk já validaram os dados da estratégia.
53. `panel_mode: shadow` por defeito para não alterar o forward test paper em curso; passar a `enforce` é decisão humana. O shadow permite medir o painel em dados futuros (votos gravados em cada alerta).
54. Hook LLM existe só como `clamp_llm` + `panel_llm_hook: false`; não há cliente LLM ligado.

## Repo 2 — freqtrade (2026-10-19)
55. Protections contam todos os trades fechados do desk (paper TAKEN e hipotéticos SKIPPED), porque medem a qualidade do sinal; no freqtrade contam trades reais.
56. Valores pré-registados (sem hyperopt): cooldown 4h; StoplossGuard 4 stops/24h → 4h; MaxDrawdown >5% do equity em 7d (≥5 trades) → 48h; LowProfitPairs ΣR<0 em 30d (≥2 trades) → 7d; Age ≥30d; volume mediano ≥ $50k/dia; vol diária ∈ [0.5%, 15%]; spread ≤ 0.5%.
57. Volume $50k/dia cortaria ~3/4 do universo live (mediana Revolut X ≈ $9k/dia). Coerente com o slippage 0.1% assumido, mas reduz alertas; fica em shadow.
58. Replay não tem bid/ask histórico → SpreadFilter = INSUFFICIENT_DATA (sem efeito) no replay; só funciona ao vivo.
59. Estratégias da comunidade: stop original −25% substituído por −8% (regra do desk). R = retorno líquido / 8%. ROI fixo do original mantido ("0": 10% / 1%).
60. Lookahead-analysis compara eventos/trades antes do corte (replay completo vs truncado); recursive-analysis só cobre o painel (o histórico 1D em cache tem ~370 velas, por isso 400 = todo o histórico).
61. `protections_mode: shadow` por defeito, para não alterar o forward test em curso; `enforce` é decisão humana.

## Repo 3 — ccxt (2026-10-19)
62. Histórico longo é Coinbase, não Revolut X: preços quase iguais (mediana do |desvio| horário 0.02–0.06%, p99 0.1–0.6%), mas volume, gaps e liquidez diferem. Os resultados medem a estratégia, não os fills Revolut X.
63. O VolumeFilter usa volume da venue do replay (Coinbase ≠ Revolut X); no replay longo o filtro é menos representativo.
64. Coinbase tem 10–11 velas 1H em falta por par em 3 anos; o resample só usa blocos completos (dias/4H com buraco são descartados).
65. Sanity cross-venue live usa até 3 tickers públicos por plano novo (raro); limiar 2% pré-registado. AAVE/NEAR tiveram horas com >7% de desvio no histórico (provável wick/iliquidez), pelo que o guard poderia vetar ocasionalmente.
66. Pré-registo do replay de 3 anos em DESK_RULES.md antes de correr; specs 01–10 sem alterações.

## Repo 4 — NautilusTrader (2026-10-19)
67. Entrada no harness = fecho da barra anterior (o Nautilus preenche MARKET contra o último preço); o replay usa a abertura seguinte. Em Coinbase é igual (p99 2–20 bps); em Revolut X há gaps (p99 15–58 bps), por isso há mais diferença por trade (p90 até 0.18R).
68. Slippage percentual (0.1%/lado) não existe no FillModel do Nautilus (só 1 tick); foi aplicada a posteriori. Fills parciais vêm do volume da barra.
69. Intenções sobrepostas no mesmo par (adds) não são reproduzidas (uma posição por par); 3–8% das trades do 01 não entram no harness.
70. Sem histórico L2/trades, a fidelidade de book/latência/fila do Nautilus não foi usada — o harness valida barras, fees e ordem de execução intrabar, não microestrutura.

## Repo 5 — Hummingbot (2026-10-19)
71. A fita pública não tem o livro histórico: posição na fila e cancelamentos são aproximados (fill só por trades através do preço, 50% da quantidade). Pode subestimar fills ao toque; o cenário optimista cobre o outro extremo.
72. Só 14 dias (1 regime); a recolha a 1 req/s demora ~1 h por 14 dias × 4 pares. Order book: só 205 snapshots, só durante a recolha (o endpoint v2 devolveu vários HTTPError).
73. Mid = mediana dos últimos 20 trades (não há BBO histórico); em DOGE (≈ 47 trades/h) o mid é ruidoso.
74. Não simulado: rebates/tiers, ordens escondidas, regras de auto-match da Revolut X, rate-limit de escrita (as ordens nunca são enviadas).
75. MM real exigiria ordens automáticas contínuas → incompatível com alerts-only/tap do utilizador; mesmo um resultado positivo ficaria só como relatório.

## Execução autónoma (2026-10-19)
76. As permissões da chave NÃO são legíveis pela API Revolut X (não há endpoint de "key info"). O bot não consegue detectar se a chave tem levantamentos; mitigação: a API não tem endpoints de levantamento/transferência, whitelist de caminhos no cliente, atestação `BOT_KEY_ATTESTED`, sub-conta recomendada.
77. Trailing/BE por cancel/replace do `tpsl`: há uma janela de milissegundos sem stop entre o cancel e a nova ordem; se a nova for rejeitada, passa a monitor local (só tão rápido quanto a cadência do executor) e notifica `STOP_FALLBACK`.
78. O `tpsl` com TP limite + SL mercado está na documentação oficial mas NUNCA foi exercitado contra a conta real (proibido nesta fase). Primeiro uso real deve ser com um valor mínimo e verificação manual na app.
79. Equity = saldo TOTAL da conta (todas as moedas × mid). Holdings do utilizador fora do bot contam para target/DD (por isso a sub-conta). O bot só vende a quantidade que ele próprio comprou.
80. Detecção de levantamento só com o alvo atingido e sem posições abertas; noutros casos um levantamento parece drawdown → REDUCE/SUSPEND (falha para o lado seguro); `rebase --confirm` resolve.
81. PaperBroker: fill da entrada só se a mínima ficar estritamente abaixo; a vela em que a ordem é colocada é ignorada; stop e TP na mesma vela → stop. Não modela fila nem fills parciais (testados com broker simulado).
82. O resultado LIVE (exec_journal.csv) ainda não alimenta o auditor; o GO continua a vir só do paper.
83. Limite de 1000 ordens/dia: o contador é do processo/estado; ordens feitas à mão na app não são contadas.

## Pesquisa de edge — vectorbt / Backtrader / Lean / qlib (2026-10-19)
84. O espaço de procura (42) é pequeno e só long-only; famílias com short/pares/funding não são testáveis em spot Revolut X. DSR/RC cobrem só estas 42 (as specs 01–12 anteriores também são tentativas; o N real é maior → correcção ainda mais dura).
85. O holdout (2025-10→2026-10) foi um ano de bear (−33% EW); estratégias de tendência long-only ficam penalizadas. O pré-teste 2020–23 cobre bull + bear e confirma dependência de regime.
86. Custos de rotação dominam o modelo cross-sectional (0.19%/lado diário). Variante maker/rebalance semanal não foi pré-registada nem testada (seria uma nova tentativa).
87. Sweep: custo aditivo na barra (aproximação ≤ 0.002 por trade vs multiplicativo); stop fixo desde a entrada (o desk usa −8% sobre o pico).
88. qlib: não é o pyqlib (sem a sua camada de dados/expressões); features re-implementadas e só 15 ativos → IC muito ruidoso. Lean e pyqlib não instalados.
89. Pré-amostra: vários pares não existiam na Coinbase em 2020–22 (SUI, NEAR, XRP relistado 2023) → carteira com menos sleeves activos nesse período.

## Repos OpenBB / yfinance / FinanceToolkit / Riskfolio / TradingAgents / Lightweight Charts (2026-10-19)
90. Macro: as séries são de mercados dos EUA (sessões em dias úteis); ao fim de semana o estado macro é o de sexta. O limite de desatualização é 4 dias (cobre fim de semana + 1 feriado).
91. Macro: o lag D+1 00:00 UTC + 1h é conservador para SPX/VIX (fecho 20–21h UTC) e DXY (≈22h UTC). O ^TNX do yfinance é o índice CBOE do yield 10y, não a série H.15 da Fed (diferença mediana 0.23%).
92. Macro: os limiares (VIX 25, DXY +2%/20d, 10y +0.30pp/20d, SPX<SMA50, veto ≥2) são escolhas próprias pré-registadas, não vêm de nenhum repo; não foram afinados depois dos resultados.
93. Macro em live: o risk_officer lê a cache `data_ext/macro`; se estiver velha e o yfinance existir, tenta refrescar (no máx. 1× por 6h por processo, timeout 10 s). As rotinas não foram alteradas: sem refresh bem-sucedido, o macro fica INSUFFICIENT_DATA (sem efeito).
94. 23_bbandrsi_macro filtra trades já gerados (não re-simula o slot libertado): aproximação; o max DD das specs da comunidade é a heurística em R do torneio (pode passar de 100%).
95. HRP: não inclui posições da mesma moeda (adds) nem o cash; com uma só posição aberta o teto é 15% × 2 × w. Correlações com 30–90 dias de dados diários são ruidosas.
96. Métricas FinanceToolkit: só descritivas. Sortino e CVaR em R por trade misturam trades de durações diferentes; as métricas de curva usam a curva diária do replay (mark-to-market).
97. Debate: sem LLM, os «argumentos» são só a tradução das métricas das camadas; não acrescenta informação nova, apenas torna a decisão auditável. A memória precisa de ≥5 trades travados e ≥5 aprovados por camada para tirar conclusões.
98. Dashboard: o gráfico do desk usa só ficheiros locais (cache do desk ou data/); se uma moeda não tiver velas em cache no timeframe pedido, o gráfico fica vazio (não pede à rede). No laptop do utilizador o estado é o do momento do zip.
