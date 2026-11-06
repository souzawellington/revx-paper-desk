# Implementation log (Texts 1→5)

## Text 1 — Loofyb0i (done earlier)
- Applied: pre-commit stop+TP (4R), immutable TP after TAKEN, EXIT NOW TAKE_PROFIT, no_hero PRIME-only, caps locked, CAP_EXCEEDED logs.
- Rejected: real trading, leverage, “10000x”.
- Tests: pass (TP exit, no TP mutation).

## Text 2 — QuantumOrb (2026-10-19)
- Applied: `desk/roles/guard.py` (max open, max total risk, daily loss halt); QUANT `COST_EV_NONPOSITIVE` via `expected_ev_r_for_plan` (win_p = threshold_win_rate); `skipped_stats.json` + downrank in risk_officer; 1h stage = … → GUARD → gate.
- Rejected: PumpSwap / bonding curve / Jito / copybots / new-token scout (not on Revolut X listed spot).
- Tests: `test_texts_2_to_5.py` guard/cost/skipped — pass.

## Text 3 — QuantGPT / RohOnChain (2026-10-19)
- Applied: `desk/findings.py` labels exactly DATA_VALIDATED | TRADE_OFF | NO_EDGE; weekly report + replay print finding; DESK_RULES paper-first + AI never sizes/orders.
- Rejected: QuantGPT SaaS, Alpaca runner, “hedge-fund data” claims.
- Tests: `test_findings_labels` — pass.

## Text 4 — 24/7 desk / eng_khairallah1 (2026-10-19)
- Applied: `desk/state/KILL` + `python -m desk kill|unkill`; exit_clerk EXIT NOW KILL_SWITCH; daily_loss_halt_pct 3%; max_open_positions 5; risk_officer+gate respect GUARD; `desk/untrusted.py` wrap; LLM still cannot size (risk_officer pure code).
- Rejected: Claude/Anthropic/Alpaca-specific wiring.
- Tests: kill closes paper, gate blocked when killed, daily halt — pass.

## Text 5 — Miles Deutscher tournament (2026-10-19)
- Applied: 5 specs in `desk/strategies/`; `python -m desk.tournament` → `desk/state/tournament_report.md`; fees/slippage; findings labels; no auto-promote.
- Result (BTC/ETH/SOL): all TRADE_OFF / none DATA_VALIDATED; live desk unchanged (FVG long).
- Rejected: scraping 50 TradingView strategies.
- Tests: tournament runs + report exists — pass.

## Repo 1 — virattt/ai-hedge-fund (MIT) (2026-10-19)
- Lido: README/VISION (v2 `hedge_fund/`: signals → portfolio/construction → risk/limits → ledger) e o v1 do histórico git (`src/agents/technicals.py`, `risk_manager.py`, `portfolio_manager.py`, `sentiment.py`). Projeto educacional, "não faz trades".
- Aplicado (`desk/panel.py`): painel de 5 analistas determinísticos (trend_4h, momentum_1d, mean_reversion_4h, volatility_1d, btc_regime_1d) com voto bullish/neutral/bearish + confiança e consenso ponderado peso×confiança (fórmula do `technicals.py`); redutores do `risk_manager.py` só para baixo (correlação com posições abertas, teto por volatilidade ≤15%); princípio do `risk/limits.py` ("conviction requests, risk disposes"; exposição cortada não é redistribuída).
- Integrado: `risk_officer` grava o voto de cada analista em `trade_plan.csv` (coluna `panel`, com migração do cabeçalho em `store.append`); `gate` mostra a linha "Painel" no texto e `data.panel` no outbox; `replay` + 2 specs no torneio (06 só-veto, 07 veto+redução). `panel_mode: shadow` por defeito (sem efeito no desk live).
- Rejeitado: personas de ações (Buffett, Munger, Graham, Lynch, Druckenmiller, Burry, Wood, …), fundamentals/valuation/P-E/insider/earnings/PEAD, Financial Datasets API, PM e personas via LLM pago, short/long-short/dollar-neutral, sentimento de notícias (sem fonte cripto gratuita fiável; qualquer texto teria de passar por untrusted_wrap), Hurst/stat-arb (ruidoso com 1 ano de dados), aumentos de tamanho do risk_manager (1.05×/1.10×, 25%).
- Resultado (replay holdout 60/40, parâmetros fixados antes): o painel corta perdas mas não cria edge. Ver `desk/state/panel_report.md`. Nenhum DATA_VALIDATED.
- Testes: `tests/test_panel.py` (13) — 76 passam no total.

## Repo 2 — freqtrade/freqtrade (GPL-3.0) (2026-10-19)
- Lido: protections (StoplossGuard, MaxDrawdown, CooldownPeriod, LowProfitPairs), pairlists (VolumePairList, AgeFilter, VolatilityFilter, SpreadFilter, RangeStability…), optimize/analysis (lookahead, recursive), docs de ROI/trailing/hyperopt/edge/FreqAI; freqtrade-strategies (GPL-3.0).
- Licença: GPL-3.0 → nada copiado nem vendorizado; ideias re-implementadas do zero a partir da documentação/descrição. O projeto não depende de freqtrade nem de ccxt.
- CCXT 4.5.88 (o que o freqtrade fixa) TEM `revolutx` (spot, `certified: False`, createOrder disponível). O freqtrade não o lista como suportado/testado. NÃO configurado, sem dry-run/live contra conta nenhuma.
- Aplicado: `desk/protections.py` (4 protections + 4 filtros, veto-only, `protections_mode: shadow` por defeito) ligado ao risk_officer (coluna `prot` em trade_plan.csv), gate (linha "Protections" + `data.protections` no outbox) e replay; `desk/analysis.py` (lookahead + recursive); `desk/community.py` (BbandRsi, ADXMomentum re-implementados, hard-stop −8%); torneio specs 08/09/10 pré-registadas.
- Rejeitado: trailing stop e ROI table no desk live (alteram saídas pré-comprometidas; só como spec de torneio via ROI das estratégias da comunidade), hyperopt (overfitting com 1 ano de dados), Edge (descontinuado e dimensiona para cima), FreqAI (ML pesado sem dados suficientes), futures/short/leverage, execução freqtrade.
- Resultado: protections reduzem perdas/DD e melhoram OOS, mas expectancy continua negativa; estratégias da comunidade ≈ 0R e abaixo dos limiares. Nenhum DATA_VALIDATED. Ver `desk/state/freqtrade_report.md`.
- Testes: `tests/test_freqtrade_ideas.py` (15) — 91 passam no total.

## Repo 3 — ccxt/ccxt (MIT) (2026-10-19)
- Dependência OPCIONAL (`requirements-optional.txt`: ccxt==4.5.88, instalado só no venv do desk). O desk funciona sem ela (sanity → INSUFFICIENT_DATA).
- Aplicado: `desk/ccxt_data.py` — `PublicOnly` (recusa credenciais; só load_markets/fetch_ohlcv/fetch_ticker/markets; enableRateLimit), paginação 1H só com velas fechadas, relatório de qualidade (gaps/inválidas), `compare_series` (data-quality entre fontes), `cross_venue_check`/`live_sanity`. risk_officer: `XVENUE_DEVIATION` dentro das protections (shadow). Testes isolados da rede (`tests/conftest.py`).
- Dados: Coinbase público, 15 pares USD, 1H, 2023-10-20 → 2026-10-19 (26 270 velas/par; 10–11 velas em falta, 0 inválidas) em `data_ext/coinbase/` (+ manifest.json). Venues testadas: coinbase/kraken/bitstamp/binanceus OK; binance.com bloqueado (HTTP 451, região).
- Revisão do `revolutx` do CCXT vs `bot/revolutx/client.py`: mensagem assinada idêntica (timestamp ms + MÉTODO + `/api/1.0/...` + query sem `?` + body JSON minificado), Ed25519 base64, mesmos headers, mesmos endpoints públicos (`1.0/public/candles/{symbol}`, `1.0/public/tickers`, `1.0/public/configuration/pairs`), taker 0.09%/maker 0%. Nenhum bug encontrado. Diferenças: o CCXT envia `until=agora` por defeito e declara limite de 50 000 velas por pedido (o nosso pede janelas de 100 — mais pedidos, não errado; limite do CCXT não verificado); CCXT usa `2.0/public/order-book`, que não usamos; vírgulas em `symbols` são url-encoded no CCXT e literais no nosso (ambos assinam exactamente o que enviam). Não foi criada nenhuma instância revolutx com credenciais.
- Rejeitado: CCXT como caminho de execução; qualquer endpoint privado; ccxt.pro/websockets; binance.com (bloqueado).
- Resultado: ver `desk/state/ccxt_report.md`. Nenhum DATA_VALIDATED com 3 anos.

## Repo 4 — NautilusTrader (LGPL-3.0) (2026-10-19)
- Instalado num venv à parte (`/workspace/.venv-nautilus`, 1.231.0); usado como biblioteca, sem modificar nem vendorizar (LGPL ok para uso opcional não distribuído no zip).
- Aplicado: `desk/intents.py` (exporta entradas/stops/TPs/saídas forçadas do replay e das specs 09/10); `tools/nautilus_harness.py` (BacktestEngine, conta CASH, MakerTakerFeeModel 0%/0.09%, stop trailing/BE do desk, variantes parity/maker_tp, fills parciais, entry void); replay grava `tp` por trade.
- Não usado: adapters live/TradingNode, L2/order-book e latência (sem dados L2/ticks históricos de Revolut X), FreqAI-like/ML.
- Resultado: replay validado (≤0.006R/trade mediana); custos/slippage dominam; nenhum DATA_VALIDATED. `desk/state/nautilus_report.md`.
- Testes: `tests/test_nautilus_harness.py` (4; o smoke test corre o harness no venv opcional se existir).

## Repo 5 — Hummingbot (Apache-2.0), 2026-10-19
- Sem conector Revolut X no Hummingbot; nada instalado/ligado. Ideias re-implementadas (pure MM + skew de inventário Avellaneda-Stoikov).
- `desk/revx_tape.py`: recolha PÚBLICA da fita de trades (`/api/1.0/public/trades/all`, com lado do agressor) e snapshots do order book (`/api/2.0/public/order-book`), 1 req/s, retomável. `data_tape/`: 14 dias × BTC/ETH/SOL/DOGE (181k trades) + 205 snapshots.
- `desk/mm_sim.py`: simulador determinístico long-only (fills pessimistas: latência 2 s, só trades do agressor oposto através do preço, 50% da quantidade; hard-stop −8% e liquidação a taker; ≤ 576 ordens/dia), κ ajustado in-sample, holdout 60/40, R = PnL/(notional×8%), auditor congelado; diagnóstico optimista não promovível.
- Specs pré-registadas `11_mm_as`, `12_mm_wide`; params `mm_*` em DESK_RULES.
- Resultado: 8/8 TRADE_OFF (todas com expectancy negativa: −5 a −54 bps/rt, −0.006 a −0.067R); optimista também negativo (7/8). Arbitragem inviável. `desk/state/hummingbot_report.md`, `mm_report.json`, `mm_summary.txt`.
- Testes: `tests/test_mm_sim.py` (10, sem rede).

## Execução autónoma (DESLIGADA por defeito), 2026-10-19
- `live/executor.py` (fora de `desk/`, que continua sem chamadas de ordem): loop idempotente `run_once` — gates duros, reconciliação (saldos + ordens + client_order_id), equity/DD/halt/target, gestão (stop do broker, BE/trailing −8% por cancel/replace, âncora 1D, TTL/void/parciais) e entradas limit post-only.
- `live/brokers.py`: `LiveBroker` (RevolutXClient assinado + whitelist de caminhos HTTP; sem cancel-all; nenhum endpoint de transferência) e `PaperBroker` (mesma interface, velas públicas, fills pessimistas) para `paper_autonomous`.
- `bot/revolutx/client.py`: `place_tpsl`, `place_conditional`, `historical_orders`, `order_fills` (docs oficiais revolut-x-api-for-llm.md).
- DESK_RULES: secção «Execução autónoma» + params `execution_mode: off`, `live_confirm_phrase`, `target_balance`, `exec_*`; `rules.py` valida o modo e tranca DD reduce ≤ 15% / suspend ≤ 30%. Gate: em modo autónomo os ENTRY passam a notificação (sem TAKEN/SKIPPED); em `off` nada muda.
- `GO_LIVE.md` (passo a passo). Testes: `tests/test_executor.py` (25, broker/cliente simulados; nenhuma chamada à conta real).

## Pesquisa de edge — vectorbt / Backtrader / Lean / qlib (worker de pesquisa), 2026-10-19
- Pré-registo em DESK_RULES («Pesquisa de edge» + adenda spec 15) antes de cada corrida.
- `desk/research/sweep.py`: motor numpy (ideia vectorbt) — 42 configs pré-registadas × 15 pares, execução na abertura seguinte, stop −8%, 0.19%/lado; Sharpe, DSR (Bailey & López de Prado), White's Reality Check (bootstrap estacionário), walk-forward 12m/3m, holdout intocado de 12 meses + Revolut X.
- `desk/research/xcheck.py`: o mesmo sinal re-executado em vectorbt 1.2 e Backtrader 1.9 (venv `/workspace/.venv-research`): nº de trades idêntico, retornos próximos.
- `desk/research/xsec_ml.py`: ranking cross-sectional estilo qlib (Alpha158-subset, LightGBM; fallback ridge sem lightgbm), IC/rank-IC, top-3 long-only com custos/stop.
- `desk/research/presample.py`: teste em dados nunca vistos (Coinbase 1D 2020-10→2023-10 via CCXT público) → `data_ext/coinbase_1d_presample/`.
- Specs 13_sweep_best, 14_xsec_lgbm_top3, 15_tsmom60d_presample. Relatório `desk/state/research_report.md` (+ research_*.json).
- Resultado: nada DATA_VALIDATED (13 NO_EDGE; 14 TRADE_OFF com expectancy negativa; 15 TRADE_OFF). Lean não instalado (C#/.NET/Docker). Testes: `tests/test_research_sweep.py` (6), `tests/test_research_xsec.py` (6).

## Repos OpenBB · yfinance · FinanceToolkit · Riskfolio-Lib · TradingAgents · Lightweight Charts (worker de dados/risco/interface), 2026-10-19
- **OpenBB (ODP 5.0, Apache-2.0 — já não AGPL):** instalado só num venv à parte (`/workspace/.venv-openbb`, pesado). Útil como 2.ª fonte sem chave: `cboe` (SPX, VIX) e `federal_reserve.treasury_rates` (10y). Usado como fornecedor opcional de `desk/macro.py` (`--provider openbb`) e para validar os dados do yfinance (`python -m desk.macro compare`). DXY não existe sem chave. Não vendorizado; não é dependência. Rejeitado: OpenBB Workspace (SaaS), providers pagos/com chave, equity fundamentals, MCP server.
- **yfinance (Apache-2.0):** dependência OPCIONAL (requirements-optional.txt; instalada no venv do desk). `desk/macro.py`: ^GSPC, ^VIX, DX-Y.NYB, ^TNX diários desde 2014 em `data_ext/macro/` + BTC-USD diário desde 2014-09 (só para o estudo). Point-in-time D+1 00:00 UTC + 1h; 4 flags; veto ≥2 flags; `macro_mode: shadow`. Ligado ao risk_officer (coluna `macro` em trade_plan.csv), gate (linha «Macro» + `data.macro`) e replay (`macro_shadow`, `MACRO_VETO`). Pré-registo em DESK_RULES antes de descarregar dados. Estudo `python -m desk.macro_study` → `desk/state/macro_report.md`: nenhum DATA_VALIDATED; veto macro ≈ sem efeito no OOS; no BTC desde 2014 os dias RISK_OFF não foram piores.
- **FinanceToolkit (MIT):** só as métricas de risco/performance aplicáveis, re-implementadas em Python puro (`desk/metrics.py`: Sortino, VaR/CVaR históricos, Ulcer Index/UPI, Calmar, Omega, profit factor, SQN, duração do DD). Verificadas contra a lib 2.2.3 (`tools/ftk_crosscheck.py`, venv `/workspace/.venv-portfolio`): iguais à precisão de máquina. Adicionadas a `auditor.stats` (`metrics`), relatório semanal (1 linha) e `replay.score` (`metrics`). Descritivas: NÃO mudam o GO. Rejeitado: fundamentals/ratios/valuation (ações), FMP API (paga), Fama-French/CAPM/beta (sem benchmark cripto relevante), opções/fixed income.
- **Riskfolio-Lib (BSD-3):** `desk/allocation.py` HRP (pearson, single linkage, bisecção recursiva; risco MV ou CVaR histórico) re-implementado em Python puro; pesos iguais aos da Riskfolio 7.4.0 até 1e-16 (`tools/riskfolio_crosscheck.py`). Teto do candidato = min(15%, w×N×15%); só reduz; `alloc_mode: shadow`. Ligado ao risk_officer (coluna `alloc`), gate e replay. Estudo `python -m desk.alloc_study` → `desk/state/alloc_report.md`: R inalterado, DD −2 pp em 15 pares, efeito nulo em BTC/ETH/SOL. Rejeitado: média-variância/Black-Litterman com retornos esperados (sem edge para estimar), optimização com cvxpy no desk (dependência pesada), qualquer alocação que aumente tamanho.
- **TradingAgents (Apache-2.0):** comparado com o painel determinístico (`desk/panel.py`). Trazido só o desenho: `desk/debate.py` (caso bull/bear com a métrica de cada ponto, 3 vistas de risco agressivo/neutro/conservador — nenhuma acima do plano — e memória `python -m desk.debate settle` que mede R por camada/ação, no lugar das reflexões LLM). `debate_record: false` por defeito; sem LLM; sem chamadas pagas. Rejeitado: o grafo LangGraph/LLMs, analistas de fundamentals/SEC/insider, sentimento de notícias/Reddit/StockTwits, o Trader/PM que dimensiona e envia ordens.
- **TradingView Lightweight Charts v5.2.1 (Apache-2.0):** vendorizado sem alterações em `bot/dashboard_static/vendor/` (+ LICENSE, NOTICE, sha256); Chart.js/CDN removido (painel funciona offline). Dashboard: velas Revolut X com entradas/saídas/stop; drawdown em área; NOVO gráfico do desk por moeda (4H/1H/1D) com zonas FVG (topo/fundo, cor pelo estado), entrada/stop/stop BE/TP/saída das posições paper/TAKEN, planos ainda não preenchidos, trades do replay histórico (◆) e curva de equity (paper + replay). Novos GET: `/api/desk/coins`, `/api/desk/chart?coin=&tf=`, `/api/desk/equity`, `/vendor/<ficheiro whitelisted>`. Continua só-leitura (405 para POST/PUT/DELETE/PATCH; coin validada; só ficheiros locais). Atribuição TradingView no rodapé + `attributionLogo` ligado.
- Testes: `tests/test_context_layers.py` (17, offline; `conftest.py` bloqueia a rede do macro). Verificação do dashboard: servidor + curl de todas as rotas + Chrome headless (`--dump-dom`): 4 gráficos renderizados, sem erros JS.

## 2026-10-20 — Correcção dos «fantasmas» do GUARD + ensaio acelerado (paper_fast)
- Bug: `guard.open_risk_frac` contava como «slot reservado» TODO o plano do trade_plan.csv cuja posição não estivesse OPEN — incluindo CLOSED/VOID/SKIPPED. Com 4 CLOSED + 1 OPEN dava 5 ≥ 5 → MAX_OPEN_POSITIONS e o risk_officer deixou de gerar planos desde 2026-10-20 ~05:00 UTC. Agora: OPEN (não SKIPPED) + planos sem linha em positions.csv, não SKIPPED e recentes (≤ max_alert_age_hours + 1h). `guard_status.json` é escrito sempre (antes ficava o último veto).
- paper_fast (só `execution_mode: paper_autonomous`): `paper_max_open_positions: 10`, `paper_max_total_risk_pct: 0.10`, `paper_entry_mode: marketable` (executor paper compra ao ask+slippage, taker, se ≤ entrada × 1.01; senão post-only), tag `paper_fast` em trade_plan/positions/journal/exec_journal, linha separada no relatório semanal. Risco 1%, ¼-Kelly, 15%, −8%, DD, halt diário, no-hero, cost gate e limiares: inalterados.
- Testes: tests/test_paper_fast.py (+14); 2 testes antigos que assumiam `execution_mode: off` no ficheiro foram tornados independentes do modo.

## 2026-10-20: exit-grid × filter study (desk/research/exitgrid.py)
- Pre-registered 7,200 variants (desk/research/prereg_exitgrid.json). Selection was done on IS and the holdout was evaluated once, with DSR and White's Reality Check applied.
- Result: no variant validated. The top-5 IS variants (+0.16 to +0.21R IS) are all negative on the holdout (−0.22 to −0.31R). DSR = 0.004, RC p = 0.56.
- No spec was added to desk/strategies/. No change to DESK_RULES, live/, keys, or thresholds. Report: desk/state/exitgrid/REPORT.md.

## 2026-10-20 — Bot-sombra C3 NÃO VALIDADA (paper-only, aprovado pelo utilizador)
- `desk/strategies/26_c3_trend_vt_unvalidated.md` (params congelados do campeão IS), `desk/shadow/c3.py` (run-once|status|resume),
  estado em `desk/state/shadow_c3/`, outbox `SHADOW_C3_TRADE|SHADOW_C3_PAUSE` (autonomous, sem TAKEN/SKIPPED), `tests/test_shadow_c3.py` (12).
- Sem broker, sem chaves, só GET públicos; não escreve journal/positions → fora do GO do auditor e do executor. execution_mode inalterado.
- Rotina diária: `cd /workspace/revolut-crypto-bot && /workspace/.venv-desk/bin/python -m desk.shadow.c3 run-once`

## 2026-10-20 — Teto 1000 USD / reset 65 USD (≈£50) + critérios de morte (pedido do utilizador; tudo paper)
- `desk/health.py` (novo): parâmetros, avaliação dos critérios, registo de execuções/erros, `python -m desk.health [--json]` (só leitura).
- DESK_RULES: `target_balance: 1000`, `reset_balance: 65`, `kill_*`; rules.py valida kill_dd_max ≤ 20% e 0 < reset < target. execution_mode inalterado (paper_autonomous).
- live/executor.py: teto trancado até `rebase --confirm` (paper: repõe saldo simulado em 65); sonda pública BTC-USD por execução (health.json),
  equity.csv; critérios → `kill_latched` + mesma acção do KILL + outbox EXEC_KILL_AUTO; falhas de execução (502) registadas no loop/run-once;
  `unkill --confirm`. Não escreve o ficheiro global KILL (não pára o journal paper do desk).
- desk/shadow/c3.py: teto por livro (pausa; bh_btc só aviso), `rebase <livro|all> --confirm`, bh_btc critérios só informativos (SHADOW_C3_INFO),
  erros de API / NO_DATA prolongado → pausa global, kill_metrics em state.json.
- Testes: +15 (230).

## 2026-10-21 — exit_clerk filtrado pelo executor (paper_autonomous)
- Causa: `auditor.paper_fill` abre no ledger do desk (positions.csv) um fill paper para TODOS os planos (abertura 1H seguinte),
  independentemente do Bot D; o exit_clerk alertava EXIT_NOW/STALE dessas posições (ex.: DOT já fora por STOP_BROKER, LPT expirado).
- desk/exit_clerk.py: em `execution_mode: paper_autonomous`, posições com decisão PENDING que o executor não tem OPEN em
  `exec_paper_autonomous/state.json` → alerta interno (`exit_clerk_internal.jsonl`), não vai ao outbox. Ledger/journal/close_paper
  inalterados (contagem do auditor igual). TAKEN/SKIPPED humanos e modo off/live: como antes. Estado ilegível → falha aberta.
  Posições que o Bot D segura: alerta sai com texto «Informativo: o Bot D gere esta saída sozinho».
- Testes: +4 (300); test_kill_closes_paper fixa `execution_mode: off`.

## 2026-10-22 — Buracos no feed scalp forward: causa = box congelado entre sessões (não é bug do ciclo)
- Diagnóstico: o log `scalp_forward.log` tem ~10–20 min de ciclos por hora e buracos de 40–55 min DESDE o arranque (20-10),
  sem `ok:false` nem restarts. O processo (pid 7970) não morre: fica CONGELADO com o box. Prova: scalp.pid escrito às 00:16 (Londres),
  mas `ps` diz arranque 06:14 — o relógio monotónico/uptime não conta ~5h58 em que o box esteve pausado (btime recalculado).
  Os blocos activos coincidem com as rotinas/agentes (~:06–:25). Sem rate-limit, sem backoff preso, sem excepção engolida.
- Ao acordar, o ciclo recupera todas as velas 1m reais em falta (API devolve a janela completa: 41/41 para BTC/ETH/SOL no buraco
  06:26–07:06Z) e corre-as minuto a minuto, marcadas `catchup` (comportamento pré-registado no spec). Não negoceia com preços velhos
  nem com minutos sintéticos inventados por causa da pausa; mas 53/71 trades forward até agora são catchup (spread fixo do replay,
  sem book ao vivo). Recusar trades em catchup mudaria o spec congelado → exigiria novo id/pré-registo; NÃO alterado.
- desk/scalp/run.py: `report()` acrescenta `catchup_trades` por livro; `status` mostra «catchup k/n» no FORWARD (só leitura/relatório;
  motor, spec, parâmetros e hash de código inalterados). Ciclo não reiniciado (não era preciso).
- Testes: +1 (301) — pausa de 50 min recuperada minuto a minuto sem buracos/sintéticos, catchup marcado, contagem no report.

## 2026-10-22 — METIS: EXIT_NOW do exit_clerk vs Bot D aberto → diferença legítima; corrigido buraco do stop no PaperBroker
- METIS-USD (P-METIS-USD-1792425600000): Bot D comprou às 11:11:45Z a 3.85385 (stop 3.816). O ledger do desk (auditor.paper_fill)
  abre o fill na vela 1H 11:00Z e o exit_clerk avalia essa MESMA vela inteira: mínimo 3.81 → STOP. Mas pelas velas 1m da Revolut X
  o 3.81 foi às 11:07Z (antes do fill); depois do fill o mínimo foi 3.82 (11:12Z) > 3.816. Bot D NÃO falhou o stop.
  Às 12:00Z o máximo 3.941 ≥ entrada+1R → BE; tpsl recolocado às 13:18:03Z com stop 3.85385; mínimos desde então ≥ 3.867. Continua OPEN.
  O alerta do exit_clerk é do ledger do desk (preço de stop da vela 1H do fill), não do Bot D — nada mudado no exit_clerk/ledger.
- Bug encontrado na investigação (live/brokers.py PaperBroker.advance): para tpsl a vela 1H da colocação era ignorada («pessimista»,
  mas para stops é optimista) e a hora corrente nunca era vista → stop cego desde a colocação/recolocação (BE) até ao fim da hora, e o
  troço hora-início→recolocação da ordem antiga nunca era avaliado. Nos 18 tpsl do Bot D, 7 tiveram o stop tocado nessa janela cega
  (DOT, LPT, SENT, FLOW, MEW, ARB, SUI) e só fecharam numa vela 1H seguinte (DOT/SENT/ARB a um preço de abertura pior:
  ≈ −0.65/−0.60/−1.60R registados vs ≈ −0.19/−0.14/−1.32R se apanhados na hora). Trades passados NÃO reescritos.
- Correcção: tpsl avaliado em horas completas com velas 1H (como antes) e nas pontas parciais (desde a colocação até ao fim dessa
  hora; hora corrente até agora) com velas 1m FECHADAS que começam a partir da colocação (preços anteriores ao fill não contam).
  Sem dados 1m → comportamento antigo. Ordens limit (entradas) inalteradas. PublicMarket.candles aceita `until` (janela 1m < 1000).
  Parâmetros da estratégia inalterados. Só afecta ordens abertas daqui em diante (hoje: só o tpsl METIS; simulação em cópia: continua aberto).
- Testes: +4 (305) tests/test_paper_tpsl_minutes.py; FakeMarket de tests/test_executor.py serve velas 1m.
