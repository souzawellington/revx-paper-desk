# DESK_RULES.md: fonte única de verdade

Todos os papéis (screener, cartographer, risk_officer, gate, exit_clerk, auditor) leem ESTE ficheiro.
Os parâmetros numéricos são lidos do bloco `params` abaixo, no formato `chave: valor`. Para mudar uma regra, mude-a só aqui.
Origem: o PDF "Trade Grok Bot" (desk short-only para perpétuos USDT), espelhado para Revolut X SPOT, que é LONG-ONLY.

## Mercado
Revolut X spot, todos os pares `*-USD` ativos (exceto stablecoins/ouro tokenizado). Só compras (LONG-ONLY).

## Filtro de tendência (1D): regra das três velas, versão de alta (up-flip)
- C1 fecha em alta (close > open). Um doji (corpo ≤ doji_body_frac × amplitude) também é válido.
- O fecho de C2 fica acima do fecho de C1, e C2 não perfura o mínimo de C1.
- O corpo de C3 fecha acima do fecho de C2.
- Nem C2 nem C3 tocam o mínimo de C1 (low > C1.low).
- Dojis são válidos. C2 não precisa de ser verde.
- **Âncora = mínimo do impulso** = C1.low (o menor low de C1..C3). O flip fica válido enquanto nenhum fecho 1D ficar abaixo da âncora.
- **PRIME:** o flip 1D está ativo e o 4H está em pullback. Pullback = a última vela 4H fechada fecha abaixo da abertura E abaixo do fecho da vela 4H anterior. Um PRIME nunca é rejeitado.
- Flips de baixa (regra espelhada) ficam registados só como contexto (`context.csv`) e nunca passam adiante.

## Zonas (4H)
- FVGs de alta ao longo de TODO o impulso, desde a âncora (mínimo) até à máxima atual. FVG entre as velas i-1, i, i+1: `low[i+1] > high[i-1]` → zona [high[i-1], low[i+1]].
- As zonas formam uma escada, ordenada de cima para baixo.
- Uma zona fica TESTED quando um pavio entra nela, mesmo parcialmente (`low ≤ zone_top`), numa vela posterior à formação.
- Uma zona fica INVALID quando uma vela 4H fecha abaixo de zone_bottom.

## Confirmação (1H)
Definição própria (o PDF diz apenas "Confirmation: 1H"; ver GAPS). Depois do teste, a primeira vela 1H fechada que cumpra as três condições:
- `close > open`;
- `close > zone_top`;
- nenhum fecho 1H abaixo de `zone_bottom` desde o teste.

Entrada = fecho dessa vela 1H. Stop = mínimo do pavio desde o teste. Stop efetivo = max(stop, entrada × (1 − hard_stop_pct)). Uma zona confirmada gera um só plano. Uma confirmação mais antiga que max_alert_age_hours (por exemplo, encontrada na primeira execução ou depois de uma paragem) fica EXPIRED e não é alertada.

## Risco
- `risk_pct` do equity por trade.
- Adicionar `add_risk_pct` só depois de a entrada anterior na mesma moeda estar em breakeven. Breakeven = o preço já atingiu entrada + be_trigger_r × R; a partir daí o stop dessa entrada sobe para a entrada.
- Tamanho = min(tamanho pelo risco, quarter-Kelly do ledger quando disponível e com n ≥ 30, max_position_frac × equity).
- Cada plano grava `tp_price` no momento do plano; immutable após TAKEN.
- O hard-stop de −8% (sobre a entrada ou o pico local) aplica-se SEMPRE.
- Equity: saldo read-only da Revolut X. Se o saldo for inferior a min_live_equity, usa-se paper_equity.

## Saídas (pré-comprometidas — Texto 1 / Loofyb0i)
- **Antes da entrada**, cada plano TEM de ter `stop` E `tp_price` escritos. Depois de TAKEN, NADA os altera, excepto a regra existente de breakeven (só o stop sobe para a entrada; o TP nunca muda).
- Take-profit em `take_profit_r` × R, com R = entrada − stop. `tp_price = entrada + take_profit_r × (entrada − stop)`.
- Fecho 1D abaixo da âncora → EXIT NOW, imediatamente.
- Stop do plano, hard-stop −8%, ou take-profit atingido → EXIT NOW (regra `TAKE_PROFIT` no TP). Nunca segurar além do TP «só mais um bocado».
- No mesmo candle, se stop e TP forem ambos atingidos: prevalece o STOP (conservador).
- Estado NEUTRAL (sem flip ativo, nem de alta nem de baixa) com a posição em lucro → manter.
- Posição plana durante stale_hours (|close/entrada − 1| < stale_band) → STALE, e o humano decide. Em paper, a posição mantém-se (stale_paper_policy).

## No-hero (Texto 1)
- `no_hero: true`: só planos a partir de watchlist **PRIME** + zona **CONFIRMED**. Sinais WATCH/fracos são rejeitados e registados.
- Nunca subir o tamanho para compensar um sinal fraco. `risk_pct` e `max_position_frac` (15%) estão trancados neste ficheiro.
- Qualquer plano que exigisse ultrapassar os tetos (notional > equity × max_leverage_equivalent, ou acima do teto de 15%/risco) é rejeitado e registado em `plan_rejections.csv` com motivo `CAP_EXCEEDED` / `NO_HERO_WEAK`.
- `max_leverage_equivalent: 1` = spot apenas (Revolut X). Sem alavancagem.


## Guardas de risco (Texto 2 / QuantumOrb — só o que se aplica a spot listado)
- Antes do Gate: módulo GUARD aplica vetos duros (máx. posições abertas, risco total agregado, halt de perda diária).
- QUANT cost gate: se EV esperado após fees+slippage ≤ 0 dado `take_profit_r` e distância ao stop → rejeitar (COST_EV_NONPOSITIVE).
- Aprendizado com SKIPPED: `desk/state/skipped_stats.json` (expectancy hipotética por moeda); risk_officer faz downrank/rejeita moedas com expectancy SKIPPED má.
- Rejeitado deste texto: PumpSwap, bonding curves, Jito, copybots, scout de tokens novos (impossível em Revolut X spot listado).

## Paper-first e IA (Texto 3 / QuantGPT — só o que se aplica)
- Paper primeiro até limiares congelados. A IA/LLM **nunca** coloca ordens e **nunca** dimensiona; no máximo veta/reduz.
- Findings do Auditor: exactamente `DATA_VALIDATED` | `TRADE_OFF` | `NO_EDGE` (ver `desk/findings.py`).

## Kill switch e halt diário (Texto 4)
- Se existir `desk/state/KILL`: exit_clerk encerra paper + EXIT NOW KILL em TAKEN; estágios 1h recusam novos ENTRY.
- CLI: `python -m desk kill` / `python -m desk unkill`.
- Halt diário: PnL paper do dia UTC ≤ `-daily_loss_halt_pct` × equity → sem novas entradas.
- `max_open_positions` (default 5). Qualquer texto social/news passa por `untrusted_wrap`.

## Painel de analistas (repo virattt/ai-hedge-fund, MIT — só o que se aplica a cripto spot)
- `desk/panel.py`: 5 analistas determinísticos sobre velas FECHADAS votam bullish/neutral/bearish + confiança:
  `trend_4h` (EMA 8/21/55 + ADX), `momentum_1d` (7/21/42 dias + volume), `mean_reversion_4h` (z-score 50 + Bollinger),
  `volatility_1d` (vol 21d vs média 63d), `btc_regime_1d` (BTC vs EMA50 e inclinação EMA20).
- Consenso = Σ(sinal × peso × confiança) / Σ(peso × confiança); pesos 0.25/0.25/0.20/0.15/0.15. Score > +limiar → KEEP; entre → REDUCE (`panel_neutral_mult`); < −limiar → VETO.
- Redutores do risk_manager do repo, só para baixo: correlação média com posições abertas ≥0.8 → ×0.70, ≥0.6 → ×0.85; teto de notional ajustado à volatilidade (nunca acima de `max_position_frac`).
- **O painel só pode VETAR ou REDUZIR** (size_mult ≤ 1). Nunca aumenta, nunca coloca ordens. Analista sem dados → INSUFFICIENT_DATA (abstém-se); com menos de `panel_min_votes` votos, sem efeito.
- `panel_mode`: `off` | `shadow` (default: regista os votos no plano e no alerta do outbox, sem alterar nada) | `enforce` (aplica veto/redução). Mudar para `enforce` é decisão humana.
- Hook LLM opcional `panel_llm_hook: false` (desligado). Se ligado: texto externo só via `untrusted_wrap`, resultado limitado por `clamp_llm` (só iguala/reduz).
- Rejeitado do repo: personas de ações (Buffett, Graham, Munger, Lynch, Druckenmiller, …), fundamentals/P-E/insider trades/earnings/PEAD, Financial Datasets API, PM via LLM, short/long-short.

## Protections e filtros de pares (freqtrade, GPL-3.0 — ideias re-implementadas, nenhum código copiado)
- `desk/protections.py`, só VETO de novos ENTRY (nunca abre, nunca aumenta, nunca altera stop/TP/saídas):
  CooldownPeriod (par), StoplossGuard (global), MaxDrawdown (global, PnL realizado na janela), LowProfitPairs (par);
  filtros AgeFilter, VolumeFilter (mediana volume×close 30d), VolatilityFilter (desvio-padrão log-retornos diários), SpreadFilter (bid/ask do ticker público).
- Filtro sem dados → INSUFFICIENT_DATA (sem efeito). `protections_mode`: `off` | `shadow` (default: regista motivos no plano e no alerta) | `enforce`. Mudar para `enforce` é decisão humana.
- Parâmetros abaixo pré-registados ANTES do replay (sem hyperopt). Torneio: 08 FVG+protections; 09/10 estratégias da comunidade (BbandRsi, ADXMomentum) re-implementadas com hard-stop −8%.
- Rigor (`python -m desk.analysis`): lookahead-analysis (replay truncado em vários cortes tem de reproduzir exactamente os eventos anteriores ao corte) e recursive-analysis (indicadores do painel com 150 vs 400 velas de histórico).
- Rejeitado: execução freqtrade (dry-run/live) — mesmo existindo `revolutx` no CCXT; trailing stop e ROI table no desk live (violam saídas pré-comprometidas); hyperopt; FreqAI; Edge positioning (descontinuado e aumentaria tamanho); futuros/short.

## Dados de outras venues via CCXT (MIT) — só público, dependência opcional
- `desk/ccxt_data.py`: `PublicOnly` recusa credenciais e só expõe `load_markets`/`fetch_ohlcv`/`fetch_ticker` (+ `markets`); `enableRateLimit` sempre. Nunca cria instância com chaves, nunca chama endpoints privados/ordens. CCXT nunca é caminho de execução.
- Histórico longo: `python -m desk.ccxt_data fetch --venue coinbase --days 1095 --out data_ext/coinbase` (1H, pares USD). Replay/torneio com `--data-dir data_ext/coinbase`.
- **Pré-registo (2026-10-19, antes de ver resultados):** Coinbase, 1095 dias até à última hora fechada, os mesmos 15 pares do cache Revolut X, specs 01–10 SEM alterações de parâmetros, holdout 60/40 por tempo, universos BTC/ETH/SOL e 15 pares. Os limiares congelados decidem; nenhum spec é promovido automaticamente. Os resultados medem a estratégia noutra venue (fills/custos de Revolut X continuam os do DESK_RULES).
- Sanity cross-venue (shadow, dentro das protections): mid Revolut X vs mediana de `xvenue_venues`; |desvio| > `xvenue_max_dev` → `XVENUE_DEVIATION` (veto só em `protections_mode: enforce`). Sem ccxt/rede/ticker → INSUFFICIENT_DATA (sem efeito).

## Verificação NautilusTrader (LGPL-3.0) — opcional, só simulação local
- `desk/intents.py` exporta as intenções (entrada, stop, TP, saída forçada) das specs; `tools/nautilus_harness.py` re-executa-as no BacktestEngine (venv `/workspace/.venv-nautilus`): conta CASH spot, maker 0% / taker 0.09%, stop trailing −8% + BE como o desk.
- Fora de `desk/` de propósito (as ordens são simuladas; `desk/` continua sem qualquer chamada de ordem). Sem adapters live, sem credenciais, sem rede.
- Serve para validar o replay; NÃO muda limiares nem promove specs.

## Market making passivo (ideias Hummingbot, Apache-2.0) — SÓ simulação, pré-registado 2026-10-19 antes de ver resultados
- Não existe conector Revolut X no Hummingbot; nada dele é instalado ou ligado. `desk/mm_sim.py` re-implementa a ideia (pure MM + skew de inventário Avellaneda-Stoikov) sobre a fita pública de trades (`desk/revx_tape.py`, 1 req/s, sem credenciais).
- Specs: `11_mm_as` (half-spread h = max(mm_min_half_bps, 1/κ) + 0.5·σ_requote) e `12_mm_wide` (h × mm_wide_mult). κ ajustado SÓ no in-sample. Holdout: primeiros 60% dos dias = in-sample, últimos 40% = OOS (corte por dia).
- Long-only, alvo de inventário 0%: bid só se inventário < mm_max_inv_frac da equity; ask ≤ inventário detido. Hard-stop de inventário −8% (taker + slippage). Liquidação final a taker.
- Fills pessimistas: latência mm_latency_s; só trades do agressor oposto ESTRITAMENTE através do nosso preço; só mm_queue_share da quantidade desse trade é nossa.
- Auditor: R = PnL do round-trip / (notional × 8%). Os limiares go/no-go acima NÃO mudam (+0.4R por round-trip é praticamente inatingível por construção para MM — documentado, não relaxado). Também se exige expectancy OOS > 0.
- Mesmo que passasse: execução continua NUNCA (alerts-only); MM exige ordens contínuas, portanto não há caminho para «tap do utilizador» — no máximo relatório.

## Execução autónoma (DESLIGADA por defeito) — `live/executor.py`
- `execution_mode`: `off` (defeito; nada acontece) | `paper_autonomous` (o MESMO loop autónomo contra o PaperBroker com velas públicas reais; ensaio) | `live` (ordens reais na Revolut X).
- Em modo autónomo o TAKEN/SKIPPED deixa de ser necessário; o Gate e o executor emitem NOTIFICAÇÕES (outbox `EXEC_*`) do que o bot fez.
- Gates (TODOS para qualquer ordem real): `execution_mode: live`; env `BOT_LIVE_CONFIRM` = `live_confirm_phrase`; env `BOT_KEY_ATTESTED=trade_only_no_withdraw`; último relatório semanal do auditor = GO (≤ `exec_go_max_age_days`) e stats actuais GO; ficheiro KILL ausente; `target_balance` (> 0; env `BOT_TARGET_BALANCE` sobrepõe) não atingido; halt diário 3%; DD do pico ≥ 15% → risco ×`exec_reduce_mult`, ≥ 30% → SUSPEND trancado (só `rebase --confirm`); máx. 5 posições; risco 1% / ¼-Kelly / teto 15% / cash disponível; stop −8% (hard e trailing no pico) + BE; spot long-only, sem alavancagem; tecto `exec_max_orders_day` (entradas) e ≤ 990/dia (protecção).
- Stops: do lado do BROKER (`tpsl` da Revolut X: SL a mercado + TP limite numa só ordem). Se o broker rejeitar → monitor local com venda a mercado (taker) e notificação `STOP_FALLBACK`.
- KILL: cancela as entradas pendentes do bot; `exec_kill_action: cancel_entries` mantém os stops/TP do broker; `flatten` vende tudo o que é do bot a mercado. Nunca toca em ordens/holdings que não são do bot; nunca usa cancel-all.
- Nunca deposita nem levanta: a API Revolut X não tem esses endpoints; o executor tem whitelist de caminhos HTTP (só saldos, ordens, preenchimentos e dados públicos).

## Ensaio acelerado (`paper_fast`) — 2026-10-20, a pedido do utilizador; SÓ simulação
- Activo só quando `execution_mode: paper_autonomous` E `paper_fast: true`. Em `off` ou `live` os parâmetros `paper_*` são IGNORADOS (o código verifica o modo; o executor exige também o PaperBroker).
- `paper_max_open_positions: 10` (vs 5) e `paper_max_total_risk_pct: 0.10` (= 10 × 1%) no GUARD do desk e no executor paper. Limite duro: ≤ 10 e ≤ posições × risk_pct.
- `paper_entry_mode: marketable`: o executor paper compra ao ask (taker 0.09% + slippage) se o ask ≤ entrada do plano × (1 + `paper_entry_tol` 1%); senão, limite post-only normal com `exec_entry_ttl_min`. Stop, TP e risco do plano não mudam.
- NÃO mudam: `risk_pct` 1%, ¼-Kelly, teto 15%, stop −8%, BE, DD 15%/30%, halt diário 3%, no-hero (PRIME+CONFIRMED), cost gate, limiares go/no-go.
- Todos os planos/posições/linhas do journal criados com o ensaio activo levam `tag = paper_fast` (journal.csv, positions.csv, trade_plan.csv, exec_journal.csv). O relatório semanal mostra os dois grupos em separado; o veredito conta ambos e diz também qual seria só com os normais. A estratégia de sinal é a mesma — o que muda é a concorrência (mais posições ao mesmo tempo → DD de carteira potencialmente maior).
- Correcção de bug no GUARD (mesma data): planos já CLOSED/VOID/SKIPPED ou antigos contavam como posições abertas («fantasmas») e travavam o desk em MAX_OPEN_POSITIONS 5≥5.

## Contexto macro (OpenBB Apache-2.0 / yfinance Apache-2.0) — opcional, veto-only, SHADOW; pré-registado 2026-10-19 ANTES de descarregar dados macro
- `desk/macro.py`: séries diárias públicas e gratuitas ^GSPC (S&P 500), ^VIX, DX-Y.NYB (índice do dólar), ^TNX (yield 10 anos EUA). Fornecedor `yfinance` (defeito) ou `openbb` (provider yfinance; mesmo dado). Sem chaves, sem APIs pagas. Cache em `data_ext/macro/`. Dependência opcional: sem yfinance/rede/cache → INSUFFICIENT_DATA (sem efeito).
- Point-in-time: uma vela diária com data D só é usável a partir de D+1 00:00 UTC + `macro_lag_hours`. Série com última vela usável mais antiga que `macro_max_stale_days` → INSUFFICIENT_DATA para essa série.
- Flags (sobre a última vela usável): EQ_DOWN = ^GSPC < SMA50; VOL_STRESS = ^VIX > `macro_vix_high`; USD_UP = DXY 20 velas > +`macro_usd_up`; RATES_UP = ^TNX 20 velas > +`macro_rates_up` pontos.
- Com < `macro_min_series` séries calculáveis → INSUFFICIENT_DATA. Nº de flags ≥ `macro_veto_flags` → VETO (RISK_OFF); 1 flag → CAUTION (sem efeito); 0 → OK.
- `macro_mode`: `off` | `shadow` (defeito: regista no plano e no alerta) | `enforce` (só veta novos ENTRY). Nunca aumenta, nunca abre, nunca toca em stops/TP/saídas. `enforce` é decisão humana.
- Teste pré-registado (sem afinar parâmetros depois de ver resultados): specs 21_fvg_macro_veto (01 + veto ≥2 flags), 22_fvg_macro_strict (01 + veto ≥1 flag), 23_bbandrsi_macro (09 + veto ≥2 flags, filtro aplicado ao sinal) (ids 21+ para não colidir com o worker de pesquisa). Universos: Revolut X 1 ano 15 pares; Coinbase 3 anos 15 pares e BTC/ETH/SOL. Holdout 60/40 por tempo. Estudo extra com BTC-USD diário yfinance desde 2014: retorno BTC a 30 dias após dias RISK_OFF vs restantes, separado IS/OOS 60/40. Critério: o macro só "ajuda" se a expectancy OOS melhorar vs a spec base; os limiares congelados continuam a decidir GO; nada é promovido automaticamente.

## Alocação HRP / CVaR (Riskfolio-Lib BSD-3 — fórmulas re-implementadas, verificadas contra a lib) — só REDUZ, SHADOW; pré-registado 2026-10-19 antes de correr
- `desk/allocation.py`: Hierarchical Risk Parity (López de Prado; como `HCPortfolio(model="HRP", codependence="pearson", linkage="single")`) sobre retornos 1D FECHADOS do candidato + posições abertas (últimos `alloc_lookback_days`, datas comuns). Medida de risco `alloc_rm`: `MV` (variância) ou `CVaR` (histórico, α 5%, fórmula `CVaR_Hist` da Riskfolio).
- Teto do candidato = min(`max_position_frac`, w_HRP × N × `max_position_frac`) × equity, N = nº de activos (abertos + candidato). Se o candidato for igual aos outros, w = 1/N → teto 15% (sem efeito). Só pode REDUZIR (nunca acima do tamanho pelo risco nem de 15%); não redistribui o corte; não mexe nas posições abertas.
- Sem posições abertas ou < `alloc_min_days` dias comuns → INSUFFICIENT_DATA (sem efeito).
- `alloc_mode`: `off` | `shadow` (defeito: regista no plano e no alerta) | `enforce` (aplica o teto). `enforce` é decisão humana.
- Teste pré-registado: specs 24_fvg_hrp_mv (01 + HRP MV enforce) e 25_fvg_hrp_cvar (01 + HRP CVaR enforce), mesmos universos do macro (Revolut X 1 ano 15 pares; Coinbase 3 anos 15 pares e BTC/ETH/SOL), holdout 60/40. Como o R por trade é definido pelo preço (entrada/stop/saída), um redutor de tamanho NÃO pode mudar WR nem expectancy em R; o teste mede só PnL, max DD e métricas da curva. Nada é promovido automaticamente.

## Debate bull/bear + memória (ideias TradingAgents, Apache-2.0) — determinístico, sem LLM, DESLIGADO por defeito
- `desk/debate.py`: a partir das camadas já gravadas no plano (painel, macro, protections, HRP, EV após custos) monta caso bull / caso bear, três vistas de risco (agressivo = tamanho do plano, nunca acima; neutro = painel; conservador = menor multiplicador de todas as camadas) e o veredito que essas camadas aplicariam. Só regista; nunca aumenta, nunca decide sozinho, nunca coloca ordens.
- `debate_record: false` (defeito). Se `true`, o gate acrescenta uma linha «Debate» ao alerta e `data.debate` ao outbox.
- Memória: `python -m desk.debate settle` junta planos e resultados do journal e mede o R realizado por camada/ação (o que o TradingAgents faz com reflexões LLM). Relatório só-leitura; não altera parâmetros nem limiares.
- Rejeitado do repo: LLMs (pagos ou não), personas de fundamentals/SEC/insiders, sentimento de notícias/StockTwits/Reddit sem fonte cripto fiável (se algum dia entrar: untrusted_wrap e só veto/redução), o "Trader"/"Portfolio Manager" que decide tamanho e envia ordens.

## Teto de saldo e critérios de morte — 2026-10-20, a pedido do utilizador (`desk/health.py`)
- **Teto `target_balance: 1000` USD** (o utilizador corrigiu: mil, não um milhão) em TODOS os bots: executor (Bot D, paper_autonomous $65), C3 com tetos, C3 sinal puro e B&H BTC. Ao atingir: pausa TRANCADA (sem novas entradas; stops/TP continuam), outbox «teto atingido, sacar e deixar o saldo inicial» (prefixo SIMULADO em paper). Nunca retoma sozinho, mesmo que o saldo desça.
- **Reinício `reset_balance: 65` USD ≈ £50.** O bot nunca deposita nem levanta. Rebase manual: `python -m live.executor rebase --confirm` (paper: repõe o saldo simulado em 65, só sem posições/ordens abertas; live: o utilizador levanta na app e o rebase só reinicia pico/dia/teto) e `python -m desk.shadow.c3 rebase <c3|c3_raw|bh_btc|all> --confirm`.
- `target_balance > 0` NÃO activa live: continuam obrigatórios `execution_mode: live`, `BOT_LIVE_CONFIRM`, `BOT_KEY_ATTESTED`, auditor GO e chave de trading (testado).
- **Critérios de morte** (avaliados em cada `run-once`; disparo → KILL/pausa trancada + outbox):
  - DD forward > `kill_dd_max` 20% (executor; C3 sinal puro). C3 com tetos mantém 14% (1,2× o pior DD OOS com tetos; mais estrito). Executor: suspenso enquanto o teto está trancado (o levantamento pareceria DD).
  - Sharpe < 0 nos últimos 365 dias (só mensurável com 12 meses de histórico forward).
  - Divergência > 2 p.p. em 30 dias: C3 = paper vs réplica do backtest nas mesmas velas; executor = retorno do PaperBroker vs retorno do journal paper do desk (mesmos sinais, modelo de fills do desk) — proxy documentado, não um backtest independente.
  - Dados Revolut X ausentes/stale > 3 dias (executor: sonda pública BTC-USD em cada execução; C3: última vela diária válida da Revolut X).
  - Erros de API: ≥ 3 execuções seguidas a falhar E ≥ 24 h a falhar, ou ≥ 50% de falhas em 7 dias (≥ 20 execuções).
- KILL do executor = estado `kill_latched` + a mesma acção do KILL (`exec_kill_action`: cancela entradas; stops/TP ficam). NÃO escreve o ficheiro global `desk/state/KILL` para não parar o journal paper do desk (amostra do auditor). Limpar: `python -m live.executor unkill --confirm` (decisão humana). C3: `python -m desk.shadow.c3 resume <livro>`.
- B&H BTC é só baseline de comparação: DD/Sharpe/teto geram aviso, mas continua a correr.
- Monitor só-leitura: `python -m desk.health` (equity, distância ao teto, cada critério vs limite).

## Execução
Por defeito NUNCA (`execution_mode: off`): só alertas, chave só de leitura, nenhum módulo de `desk/` chama endpoints de escrita. A única via de ordens é `live/executor.py`, com os gates acima. Não activar trading real; não chase de «10000x».

## Go/no-go (CONGELADO; nunca alterar depois de ver resultados)
trades ≥ 40 | win rate ≥ 33% | expectancy ≥ +0.4R | max DD ≤ 20%

```params
quote: USD
exclude_bases: USDC,USDT,PAXG,XAUT,DAI,EURC,USDS,PYUSD
doji_body_frac: 0.1
flip_lookback_days: 10
watchlist_max_age_days: 30
risk_pct: 0.01
add_risk_pct: 0.005
max_adds: 1
be_trigger_r: 1.0
be_move_stop: true
max_position_frac: 0.15
hard_stop_pct: 0.08
use_kelly_ledger: true
paper_equity: 10000
min_live_equity: 10
taker_fee: 0.0009
slippage: 0.001
stale_hours: 72
stale_band: 0.01
stale_paper_policy: hold
alert_paper_exits: true
gate_chart_bars_4h: 90
take_profit_r: 4
no_hero: true
max_leverage_equivalent: 1
max_alert_age_hours: 2
threshold_trades: 40
threshold_win_rate: 0.33
threshold_expectancy_r: 0.4
max_open_positions: 5
max_total_risk_pct: 0.05
daily_loss_halt_pct: 0.03
skipped_downrank_min_n: 5
skipped_downrank_max_ev: -0.2
cost_gate: true
threshold_max_dd: 0.20
panel_mode: shadow
panel_consensus_threshold: 0.2
panel_min_votes: 3
panel_neutral_mult: 0.5
panel_vol_cap: true
panel_llm_hook: false
protections_mode: shadow
prot_cooldown_hours: 4
prot_slguard_lookback_h: 24
prot_slguard_trades: 4
prot_slguard_lock_h: 4
prot_maxdd_lookback_h: 168
prot_maxdd_min_trades: 5
prot_maxdd_pct: 0.05
prot_maxdd_lock_h: 48
prot_lowprofit_lookback_h: 720
prot_lowprofit_trades: 2
prot_lowprofit_min_r: 0
prot_lowprofit_lock_h: 168
filt_min_days: 30
filt_min_quote_vol: 50000
filt_vol_days: 10
filt_min_vol: 0.005
filt_max_vol: 0.15
filt_max_spread: 0.005
xvenue_check: true
xvenue_max_dev: 0.02
xvenue_venues: coinbase,kraken,bitstamp
mm_capital_usd: 65
mm_order_usd: 20
mm_requote_s: 300
mm_latency_s: 2
mm_queue_share: 0.5
mm_min_half_bps: 2
mm_max_inv_frac: 0.6
mm_wide_mult: 2
execution_mode: paper_autonomous
live_confirm_phrase: EU ACEITO ORDENS REAIS NA REVOLUT X
target_balance: 1000            # TETO (USD) pedido do utilizador 2026-10-20 («1000»): ao atingir → pausa trancada + aviso; NÃO activa live
reset_balance: 65               # USD ≈ £50: saldo de reinício após o rebase manual (paper: reposto; live: o utilizador levanta na app)
# --- critérios de morte (desk/health.py) — KILL/pausa automática + notificação ---
kill_dd_max: 0.20               # DD forward > 20% (C3 com tetos: 14%, mais estrito; B&H BTC: só informativo)
kill_sharpe_days: 365           # 12 meses forward com Sharpe < 0
kill_diverge_days: 30
kill_diverge_max: 0.02          # |paper − referência| > 2 p.p. em 30 dias
kill_data_stale_days: 3         # sem dados válidos da Revolut X há > 3 dias
kill_api_fail_hours: 24         # falhas seguidas ≥ 3 execuções E ≥ 24 h (o 502 de 3 h de 2026-10-20 NÃO dispara)
kill_api_fail_min_runs: 3
kill_api_rate_days: 7           # ou ≥ 50% das execuções a falhar em 7 dias (com ≥ 20 execuções)
kill_api_rate_max: 0.5
kill_api_rate_min_runs: 20
paper_autonomous_equity: 65
exec_entry_tol: 0.002
exec_entry_ttl_min: 120
exec_max_orders_day: 900
exec_dd_reduce: 0.15
exec_dd_suspend: 0.30
exec_reduce_mult: 0.5
exec_stop_replace_min: 0.005
exec_kill_action: cancel_entries
exec_go_max_age_days: 8
# --- ensaio acelerado (paper_fast): SÓ com execution_mode: paper_autonomous; ignorado em off/live ---
paper_fast: true
paper_max_open_positions: 10
paper_max_total_risk_pct: 0.10
paper_entry_mode: marketable
paper_entry_tol: 0.01
# --- contexto macro (OpenBB/yfinance) ---
macro_mode: shadow
macro_provider: yfinance
macro_lag_hours: 1
macro_max_stale_days: 4
macro_min_series: 3
macro_veto_flags: 2
macro_vix_high: 25
macro_usd_up: 0.02
macro_rates_up: 0.30
# --- alocação HRP (Riskfolio-Lib) ---
alloc_mode: shadow
alloc_rm: MV
alloc_lookback_days: 90
alloc_min_days: 30
# --- debate (TradingAgents) ---
debate_record: false
```

## Pesquisa de edge — vectorbt / Backtrader / Lean / qlib (worker de pesquisa) — PRÉ-REGISTADO 2026-10-19 antes de correr
Código em `desk/research/`; só simulação, nada muda no desk live; limiares go/no-go CONGELADOS acima.
**Dados e cortes:** Coinbase 1H 3 anos (`data_ext/coinbase`, 15 pares). DEV = 2023-10-20 → 2025-10-19; HOLDOUT intocado = 2025-10-20 → 2026-10-18 (últimos 12 meses, avaliado UMA vez). Revolut X 1H (`data/`, ~1 ano) = segundo holdout (outra venue, mesmo período).
**Custos:** taker 0.09% + slippage 0.1% por lado (0.19%/lado); sensibilidade (não promovível) com entrada maker 0% + 0.05%.
**Execução simulada:** sinal no fecho da barra t, entrada/saída na abertura de t+1; long-only spot; stop −8% fixo desde a entrada (fill = min(abertura, stop)); após stop, só reentra depois de o sinal desligar. Carteira = 15 sleeves iguais (1/15 cada, cash quando flat).
**Espaço de procura (N = 42 configurações = 14 × 3 timeframes {1H, 4H, 1D}):**
- SMA cross (rápida, lenta) ∈ {(10,50), (20,100), (50,200)}
- Donchian breakout (entrada n, saída m) ∈ {(20,10), (55,20), (100,50)}
- TSMOM: long se close/close[L] − 1 > 0, L ∈ {20, 60, 120}
- RSI reversão (n, entra <, sai >) ∈ {(2,10,70), (14,30,55), (14,25,70)}
- Bollinger reversão (n, k) ∈ {(20,2.0), (50,2.5)}: entra close < banda inferior, sai close > média
**Selecção (regra fixa):** maior Sharpe diário anualizado no DEV. Walk-forward dentro do DEV: treino 12 meses / teste 3 meses, passo 3 meses (4 folds).
**Correcção para testes múltiplos:** Deflated Sharpe Ratio (Bailey & López de Prado, N = 42, variância dos Sharpes dos 42) e White's Reality Check (bootstrap estacionário, bloco médio 10 dias, B = 2000) contra cash e contra buy&hold equal-weight; edge só se DSR > 0.95 E p(RC) < 0.05 no DEV.
**Promoção:** a config seleccionada vira spec `13_sweep_best`; DATA_VALIDATED só se no HOLDOUT (Coinbase) passar os limiares congelados com R = retorno líquido / 8% (≥ 40 trades, WR ≥ 33%, ≥ +0.4R, DD carteira ≤ 20%) e expectancy > 0 também na Revolut X.
**qlib (re-implementação leve, sem instalar pyqlib):** ranking cross-sectional diário dos 15 pares; ~30 features estilo Alpha158 (KMID, KLEN, KUP, KLOW, KSFT, ROC/MA/STD/MAX/MIN/RSV/CORR/VMA/VSTD em janelas {5,10,20,30,60}); label = retorno abertura t+1 → abertura t+2, rankeado no dia; LightGBM fixo (lr 0.05, num_leaves 15, max_depth 4, min_data_in_leaf 50, feature_fraction 0.8, bagging 0.8, lambda_l2 10, ≤ 500 rondas, early stop 50 na validação). Treino 2023-10-20 → 2025-04-19, validação 2025-04-20 → 2025-10-19, teste = HOLDOUT. Métricas: IC, rank-IC, ICIR, t-stat; top-k = 3 long-only, rebalance diário, custos 0.19% × turnover, stop −8% diário; spec `14_xsec_lgbm_top3` sob os mesmos limiares (cada posição diária = um trade em R).
**Adenda pesquisa (pré-registada 2026-10-19, DEPOIS do holdout e ANTES de ver os dados novos):** o sweep deu NO_EDGE; no diagnóstico do holdout (não usado para selecção) `tsmom_60_24h` foi a melhor. Como o holdout já está gasto, a única validação honesta é em dados NUNCA vistos: spec `15_tsmom60d_presample` = TSMOM L=60 em 1D, mesmas regras/custos/stop, carteira dos pares disponíveis, Coinbase 1D 2020-10-20 → 2023-10-19 (período anterior a todo o DEV; via CCXT público). DATA_VALIDATED só se passar os limiares congelados nesse período (≥ 40 trades, WR ≥ 33%, ≥ +0.4R, DD ≤ 20%). Seleccionada depois de ver 42 resultados no holdout → mesmo que passe, fica só como candidata a paper forward.
