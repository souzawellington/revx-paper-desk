# GO_LIVE — como ligar a execução autónoma na Revolut X (passo a passo)

> Estado actual: **DESLIGADO** (`execution_mode: off`). Nada é enviado à Revolut X. Só ligar `live` depois de o
> relatório semanal do auditor dizer **GO** (≥ 40 trades, WR ≥ 33%, expectancy ≥ +0.4R, DD ≤ 20%) — o próprio bot recusa antes disso.

## 0. O que o bot faz sozinho em `live`
- Compra com ordem **limite post-only** (maker, 0%) ao bid ou abaixo; cancela ao fim de 120 min se não encher.
- Assim que enche, coloca **na própria Revolut X** uma ordem `tpsl`: stop-loss (a mercado) + take-profit (limite) — a protecção fica no broker mesmo que o computador desligue.
- Sobe o stop (breakeven a +1R e hard-stop −8% sobre o pico) com cancelar/recolocar; sai a mercado se o fecho diário ficar abaixo da âncora.
- Teto `target_balance: 1000` USD (DESK_RULES): ao atingir, PAUSA (sem novas entradas) e avisa «teto atingido, sacar e deixar o saldo inicial». Só retoma depois de levantares e correres `python -m live.executor rebase --confirm` (saldo inicial de referência `reset_balance: 65` USD ≈ £50). O bot nunca deposita nem levanta.
- **Nunca** deposita, levanta ou transfere (a API da Revolut X nem tem essas funções e o bot bloqueia qualquer caminho fora da lista permitida), nunca faz short, nunca usa alavancagem, nunca toca em moedas/ordens que não foram compradas por ele.

## 1. Recomendado: sub-conta só para o bot
Na Revolut X cria uma **sub-conta** e coloca lá só o capital do bot (ex. £50). Os fundos ficam isolados do resto.

## 2. Criar a chave de API (nova, só para o bot)
1. No computador: `openssl genpkey -algorithm ed25519 -out ~/.revx-trade/private.pem` e `openssl pkey -in ~/.revx-trade/private.pem -pubout -out ~/.revx-trade/public.pem`; `chmod 600 ~/.revx-trade/private.pem`.
2. Revolut X web → Perfil → **API Keys** → nova chave, cola o `public.pem`, permissão de **trading spot**. **Não** actives nada de levantamento/transferência (se a opção existir). Se der, restringe ao **IP** do computador do bot.
3. Guarda a chave de 64 caracteres. Não a partilhes nem a coloques em ficheiros do projecto.
   (A chave actual, só de leitura, continua a servir o dashboard; a de trading é outra.)

## 3. Variáveis de ambiente (no computador do bot)
```
export REVX_TRADE_API_KEY=...                         # a chave nova
export REVX_TRADE_PRIVATE_KEY_PATH=~/.revx-trade/private.pem
export BOT_KEY_ATTESTED=trade_only_no_withdraw        # confirmas que a chave NÃO tem levantamentos
# export BOT_TARGET_BALANCE=1000                      # opcional: sobrepõe o teto de DESK_RULES (target_balance: 1000 USD)
export BOT_LIVE_CONFIRM="EU ACEITO ORDENS REAIS NA REVOLUT X"
```
O bot não arranca em `live` se faltar alguma (a frase tem de ser exactamente a de `live_confirm_phrase` em DESK_RULES.md).

## 4. Ensaiar primeiro (agora)
Em `desk/DESK_RULES.md` muda `execution_mode: off` → `execution_mode: paper_autonomous`. O mesmo loop corre contra um broker simulado (saldo `paper_autonomous_equity`, velas públicas reais). Ver estado: `python -m live.executor status`.

## 5. Ligar a sério (só depois de GO)
1. Confirmar que o último `desk/state/reports/weekly_*.md` diz **GO**.
2. `execution_mode: live` em DESK_RULES.md.
3. Correr: `python -m live.executor run-once` (uma vez) ou `python -m live.executor loop --interval 300`.
4. As mensagens `EXEC_*` (comprei / vendi / stop movido / alvo atingido / bloqueado) chegam como notificações — já não há TAKEN/SKIPPED.

## 6. Alvo de saldo e levantamentos
- Atingido o alvo, o bot cancela entradas pendentes e não abre mais; as posições abertas continuam com stop/TP.
- Levanta o excedente na app (Revolut X → conta Revolut), deixando ≈ $65 (£50). O bot reconhece o levantamento (não o conta como perda) mas continua PAUSADO até correres `python -m live.executor rebase --confirm`.
- Critérios de morte (KILL automático + aviso): DD > 20%, Sharpe 12 meses < 0, divergência > 2 p.p./30 dias, dados Revolut X > 3 dias sem actualizar, erros de API ≥ 24 h seguidas. Ver `python -m desk.health`; limpar só após revisão: `python -m live.executor unkill --confirm`.
- Se um levantamento for confundido com drawdown: `python -m live.executor rebase --confirm`.

## 7. Parar / matar
- **Parar com calma**: `execution_mode: off` (o loop termina no ciclo seguinte; ordens no broker ficam).
- **KILL**: `python -m desk kill` → cancela as entradas pendentes do bot; os stops/TP do broker continuam a proteger. Para vender tudo o que é do bot a mercado: `exec_kill_action: flatten` antes do kill. Retomar: `python -m desk unkill`.
- **Emergência total**: revogar a chave em Revolut X → Perfil → API Keys e cancelar ordens na app.

## 8. Travões automáticos (não precisas de fazer nada)
Halt diário −3% · drawdown do pico ≥ 15% → risco a metade · ≥ 30% → SUSPENDE (só reabre com `rebase --confirm`) · máx. 5 posições · 1% de risco por trade, ¼-Kelly, teto 15% · ≤ 900 ordens de entrada/dia.
