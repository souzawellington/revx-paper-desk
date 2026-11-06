#!/usr/bin/env bash
# Bots Scalp 1m/5m — PAPER ONLY (preços públicos Revolut X, nenhuma ordem real, nenhuma chave).
#   tools/scalp_up.sh --ensure   -> garante que o ciclo forward (~60 s) está a correr; arranca-o se não estiver (idempotente; rotina horária)
#   tools/scalp_up.sh --loop     -> ciclo em primeiro plano (usado pelo --ensure)
#   tools/scalp_up.sh --stop | --status | --once      (--quiet: sem saída exceto erros)
# NUNCA passa chaves da Revolut ao processo (REVX_* removidas). Estado em desk/state/scalp_paper/forward/.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="${SCALP_PY:-python3}"
RUN="$ROOT/logs/run"; LOG="$ROOT/logs/scalp_forward.log"; mkdir -p "$RUN"
MODE=status; QUIET=0
for a in "$@"; do case "$a" in --ensure) MODE=ensure;; --loop) MODE=loop;; --stop) MODE=stop;; --status) MODE=status;; --once) MODE=once;; --quiet) QUIET=1;; esac; done
say(){ [ "$QUIET" = 1 ] || echo "$@"; }
alive(){ [ -f "$RUN/scalp.pid" ] && kill -0 "$(cat "$RUN/scalp.pid")" 2>/dev/null; }
rotate(){ if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5242880 ]; then tail -n 5000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi; }
case "$MODE" in
  once) env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH "$PY" -m desk.scalp run-once ;;
  loop) exec 9>"$RUN/scalp.lock"; flock -n 9 || { echo "outro ciclo scalp já tem o lock" >&2; exit 0; }
        echo $$ >"$RUN/scalp.pid"; trap 'rm -f "$RUN/scalp.pid"; exit 0' INT TERM
        while true; do rotate; env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH PYTHONUNBUFFERED=1 "$PY" -m desk.scalp loop >>"$LOG" 2>&1; echo "{\"restart\":\"$(date -Is)\"}" >>"$LOG"; sleep 10; done ;;
  ensure) if alive; then say "scalp forward OK pid $(cat "$RUN/scalp.pid")"; else
            setsid nohup "$0" --loop >/dev/null 2>&1 < /dev/null & sleep 2
            if alive; then say "scalp forward (re)arrancado pid $(cat "$RUN/scalp.pid")"; else echo "ERRO: ciclo scalp não arrancou" >&2; exit 6; fi
          fi
          # bot de notícias (news_v1, paper) tem ciclo próprio; o mesmo --ensure horário garante-o (falha aqui não afeta o scalp)
          if [ -x "$ROOT/tools/news_up.sh" ]; then "$ROOT/tools/news_up.sh" --ensure $([ "$QUIET" = 1 ] && echo --quiet) || echo "AVISO: ciclo news não arrancou" >&2; fi ;;
  stop) if alive; then kill -TERM -- "-$(cat "$RUN/scalp.pid")" 2>/dev/null || kill "$(cat "$RUN/scalp.pid")"; rm -f "$RUN/scalp.pid"; say "parado"; else say "não estava a correr"; fi ;;
  status) alive && say "a correr pid $(cat "$RUN/scalp.pid")" || say "parado"; env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH "$PY" -m desk.scalp status ;;
esac
