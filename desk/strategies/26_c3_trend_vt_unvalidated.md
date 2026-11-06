# 26 — C3 tendência BTC+ETH com vol-target — **NÃO VALIDADA / NOT VALIDATED** — só observação forward em paper

**Estado:** REJEITADA pela regra pré-registada (`desk/research/prereg_estudo.json`, sha256 `8b9d3112…28baa1`; falha V4 DSR 0,014,
V5 White RC p = 0,34, V6 Holm p = 0,17, V7 não bate o B&H BTC em Sharpe). Ver `desk/state/estudo_estrategias/RELATORIO.md` §3.
O utilizador aprovou explicitamente (2026-10-20) **apenas** uma observação forward SIMULADA com dados reais, ao lado de um B&H BTC.
Não é candidata a live, não conta para o GO do auditor, não é lida por `live/executor.py`. Tag: `c3_unvalidated`.

## Parâmetros CONGELADOS (campeão IS `C3_btc_eth_tendencia_vt:assets=BTC+ETH,n=100,vt=1`)
| parâmetro | valor |
|---|---|
| activos | BTC-USD, ETH-USD (Revolut X) |
| sinal | fecho diário > SMA(100) dos fechos (inclui o dia) → ON; senão peso 0 |
| peso-alvo (sinal puro) | ½ × min(1; 0,5 / vol30), vol30 = desvio-padrão (ddof 0) de 30 log-retornos diários × √365 |
| tetos do desk (livro principal) | min(peso, 12,5%) por activo (1% risco / −8% stop), ≤ 5 posições ⇒ máx. 25% investido |
| stop | −8% do preço médio (simula `tpsl` no broker): sai ao stop, ou à abertura se houve gap; taker + 10 bps |
| reentrada após stop | quando o sinal volta a 0, ou após 14 dias |
| banda de rebalance | só negoceia se desvio > max(1 p.p.; 20% relativo) |
| avaliação | uma vez por vela 1D FECHADA (dia de Londres na Revolut X; dia UTC no fallback Coinbase) |
| execução paper | logo após o fecho, ao preço ao vivo: compra ao ASK, vende ao BID do order book público da Revolut X; taker 0,09%. Sem livro → último fecho ± 10 bps (assumido). Sem pressuposto maker. |
| equity inicial | $65 simulados por livro |

Nota: com os tetos, o peso é 12,5% sempre que o sinal está ON (o vol-target só reduz abaixo de 12,5% se a vol30 > 200%).
Por isso o bot regista **dois livros C3**: `c3` (tetos do desk, principal: OOS Sharpe 1,00 / CAGR 9,7% / DD 11,4%) e `c3_raw`
(sinal puro da spec: OOS Sharpe 1,02 / CAGR 33% / DD 35%), mais `bh_btc` (compra $65 de BTC no 1.º dia ao ASK e segura; sem stop).

## Critérios de paragem automática (flags de pausa; retoma só manual, `resume`)
1. DD forward do livro `c3` > 14% (1,2 × pior DD OOS com tetos, RELATORIO §7); do livro `c3_raw` > 20% (limiar do auditor, §3).
2. 12 meses forward com Sharpe diário < 0 (após 365 velas).
3. Desvio > 2 p.p. em 30 dias entre o paper e a réplica do backtest (`desk.research.estudo.run_sim`) nas mesmas velas.
4. ≥ 3 dias sem velas válidas da Revolut X (o fallback Coinbase mantém a marcação, mas não "conta" como Revolut X) → pausa global.
Pausado = não negoceia (posições ficam marcadas a mercado). Sem dados nenhuns → não faz nada (NO_DATA).

## Execução / isolamento
`python -m desk.shadow.c3 run-once | status | resume [c3|c3_raw|_global]` — idempotente por vela diária.
Estado: `desk/state/shadow_c3/{state.json,trades.csv,equity.csv}`. Sem broker (`BROKER = None`), sem chaves, só GET públicos.
Outbox: `SHADOW_C3_TRADE` (entrada/saída/stop/rebalance acima da banda) e `SHADOW_C3_PAUSE`; `autonomous: true`,
`reply_options: []`, texto começa por "🧪 SIMULADO · C3 NÃO VALIDADA". Sem alterações → silêncio.
