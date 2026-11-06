# Formato do outbox (`desk/state/outbox.jsonl`)

O ficheiro é append-only, com um alerta JSON por linha. O Gate (entradas), o Exit Clerk (saídas/STALE) e o Auditor (relatório semanal) escrevem nele. O agente lê os PENDING, reencaminha `text` (e `chart_png`, se existir) ao utilizador e marca o alerta com `python -m desk outbox --ack <id>`. A decisão do utilizador sobre uma entrada é registada com `python -m desk decide <id> TAKEN|SKIPPED`, que também faz o ack.

Campos comuns:
| campo | tipo | nota |
|---|---|---|
| `id` | string | determinístico, chave de dedupe: `ENTRY:<plan_id>`, `EXIT:<pid>:<regra>`, `STALE:<pid>`, `WEEKLY:<AAAA-MM-DD>` |
| `type` | `ENTRY_ALERT` \| `EXIT_NOW` \| `STALE` \| `WEEKLY_REPORT` | |
| `created_at` | ISO-8601 UTC | |
| `status` | `PENDING` \| `RELAYED` | `RELAYED` é derivado de `outbox_acks.jsonl` |
| `coin` | `BASE-USD` ou null | |
| `text` | string | mensagem pronta a enviar (pt) |
| `chart_png` | caminho absoluto ou null | PNG (velas 4H + zonas + entrada/stop/âncora); só em ENTRY_ALERT |
| `data` | objeto | valores numéricos |

`ENTRY_ALERT`: `plan_id`, `reply_options: ["TAKEN","SKIPPED"]`. `data` inclui entry, stop, size, notional, risk_pct, effective_risk_pct, add_number, anchor_low, zone_id, zone_top, zone_bottom, equity, equity_source, sizing_binding.
`EXIT_NOW`: `pid`, `plan_id`, `rule` ∈ {STOP, STOP_GAP, HARD_STOP_8PCT, HARD_STOP_8PCT_GAP, ANCHOR_1D_CLOSE, TAKE_PROFIT, TAKE_PROFIT_GAP}. `data` inclui price, entry e mode (PAPER\|TAKEN).
`STALE`: `rule: FLAT_72H`.
`WEEKLY_REPORT`: `report_path`. `data` inclui n, win_rate, expectancy_r, max_dd e go.

Exemplo:
```json
{"id":"ENTRY:P-TST-USD-1705377600000","type":"ENTRY_ALERT","coin":"TST-USD","plan_id":"P-TST-USD-1705377600000","text":"🟢 ENTRY ALERT ...","chart_png":"/workspace/revolut-crypto-bot/desk/state/charts/ENTRY_P-TST-USD-1705377600000.png","data":{"entry":"107.0","stop":"105.95",...},"reply_options":["TAKEN","SKIPPED"],"status":"PENDING","created_at":"2026-10-19T12:40:00Z"}
```

`SHADOW_C3_TRADE` / `SHADOW_C3_PAUSE` (bot-sombra C3 NÃO VALIDADA, `desk/shadow/c3.py`): `mode: shadow_c3_unvalidated`, `tag: c3_unvalidated`, `autonomous: true`, `reply_options: []`. Notificação SIMULADA apenas — reencaminhar e fazer ack; nunca TAKEN/SKIPPED. Id: `SHADOW_C3:<AAAA-MM-DD>:TRADE` ou `SHADOW_C3:<AAAA-MM-DD>:PAUSE:<livro>`.

`SCALP_SUMMARY` (bots Scalp 1m/5m, PAPER ONLY, `desk/scalp/`): `mode: scalp_paper`, `tag: scalp_forward_v1`, `autonomous: true`, `reply_options: []`.
No máximo 1 por hora e só quando houve operações fechadas ou eventos (kill diário −2%, kill DD 20%, teto) desde o último resumo.
Id: `SCALP_SUMMARY:<AAAA-MM-DDTHH>` (hora UTC). Reencaminhar `text` e fazer `python -m desk outbox --ack <id>`; nunca TAKEN/SKIPPED.
`data`: new_trades, new_events, books{livro: trades, win_rate, expectancy_r, equity, verdict}.
