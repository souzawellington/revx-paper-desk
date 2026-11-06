# Desk "Trade Grok Bot": Revolut X spot, long-only, apenas alertas

Leia primeiro `DESK_RULES.md`, a fonte única de verdade de onde todos os papéis leem os parâmetros. O formato dos alertas está em `OUTBOX.md`.

## Papéis (cada um num módulo próprio, partilhando os CSVs de `desk/state/`)
| Papel | Comando | Lê | Escreve |
|---|---|---|---|
| Screener | `python -m desk screener [--symbols BTC,ETH]` | velas 1D/4H públicas | `watchlist.csv`, `context.csv` |
| Cartographer | `python -m desk cartographer [--confirm]` | watchlist, velas 4H/1H | `zones.csv` |
| Risk Officer | `python -m desk risk_officer` | zones, positions, saldo read-only, ledger | `trade_plan.csv`, `plan_rejections.csv` |
| Gate | `python -m desk gate` · `python -m desk decide <id> TAKEN\|SKIPPED` | trade_plan | `outbox.jsonl`, `charts/*.png`, `decisions.csv` |
| Exit Clerk | `python -m desk exit_clerk --stage 4h\|daily` | positions, velas | `outbox.jsonl` (EXIT NOW/STALE), positions |
| Auditor | `python -m desk auditor [--weekly]` · `python -m desk close <pid> <preço>` | plans, positions, journal | `positions.csv` (fills paper), `journal.csv`, `reports/` |

## Rotinas (cron, horário UTC; as velas Revolut X fecham em UTC)
```
5 * * * *     cd /workspace/revolut-crypto-bot && python -m desk.run --stage 1h
7 */4 * * *   cd /workspace/revolut-crypto-bot && python -m desk.run --stage 4h
10 0 * * *    cd /workspace/revolut-crypto-bot && python -m desk.run --stage daily
30 0 * * 0    cd /workspace/revolut-crypto-bot && python -m desk.run --stage weekly
```
- `daily`: screener → cartographer → exit_clerk(daily). Analisa cerca de 300 pares, a 1 pedido/s público, o que dá uns 5–6 min.
- `4h`: cartographer → exit_clerk(4h).
- `1h`: cartographer(confirm) → risk_officer → gate → auditor (fills paper).
- `weekly`: relatório do auditor.

Um lock impede dois estágios ao mesmo tempo, e o outbox não repete ids (dedupe).

## Replay histórico
`python -m desk.replay --symbols BTC,ETH,SOL` (ou sem `--symbols` para todos os `data/candles_*-USD_60.json`). Para análise de sensibilidade: `--set be_move_stop=false`. A opção `--set` não altera o DESK_RULES.md.

## Dashboard
`python -m bot.dashboard` mostra a secção "Desk": KPIs contra os limiares, watchlist, zonas, outbox com gráficos, posições e journal.
