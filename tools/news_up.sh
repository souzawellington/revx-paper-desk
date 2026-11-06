#!/usr/bin/env bash
# Bot de NOTÍCIAS (news_v1) — PAPER ONLY (notícias públicas + preços públicos Revolut X, nenhuma ordem real, nenhuma chave).
#   tools/news_up.sh --ensure   -> garante que o ciclo (~120 s) está a correr; arranca-o se não estiver (idempotente)
#   tools/news_up.sh --loop     -> ciclo em primeiro plano (usado pelo --ensure)
#   tools/news_up.sh --stop | --status | --once      (--quiet: sem saída exceto erros)
# Também é garantido por tools/scalp_up.sh --ensure (rotina horária). Estado em desk/state/news_paper/forward/.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="${NEWS_PY:-python3}"
RUN="$ROOT/logs/run"; LOG="$ROOT/logs/news_forward.log"; mkdir -p "$RUN"
MODE=status; QUIET=0
for a in "$@"; do case "$a" in --ensure) MODE=ensure;; --loop) MODE=loop;; --stop) MODE=stop;; --status) MODE=status;; --once) MODE=once;; --quiet) QUIET=1;; esac; done
say(){ [ "$QUIET" = 1 ] || echo "$@"; }
alive(){ [ -f "$RUN/news.pid" ] && kill -0 "$(cat "$RUN/news.pid")" 2>/dev/null; }
rotate(){ if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5242880 ]; then tail -n 5000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi; }
case "$MODE" in
  once) env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH "$PY" -m desk.news run-once ;;
  loop) exec 9>"$RUN/news.lock"; flock -n 9 || { echo "outro ciclo news já tem o lock" >&2; exit 0; }
        echo $$ >"$RUN/news.pid"; trap 'rm -f "$RUN/news.pid"; exit 0' INT TERM
        while true; do rotate; env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH PYTHONUNBUFFERED=1 "$PY" -m desk.news loop >>"$LOG" 2>&1; echo "{\"restart\":\"$(date -Is)\"}" >>"$LOG"; sleep 15; done ;;
  ensure) if alive; then say "news forward OK pid $(cat "$RUN/news.pid")"; else
            setsid nohup "$0" --loop >/dev/null 2>&1 < /dev/null & sleep 2
            if alive; then say "news forward (re)arrancado pid $(cat "$RUN/news.pid")"; else echo "ERRO: ciclo news não arrancou" >&2; exit 6; fi
          fi ;;
  stop) if alive; then kill -TERM -- "-$(cat "$RUN/news.pid")" 2>/dev/null || kill "$(cat "$RUN/news.pid")"; rm -f "$RUN/news.pid"; say "parado"; else say "não estava a correr"; fi ;;
  status) alive && say "a correr pid $(cat "$RUN/news.pid")" || say "parado"; env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH "$PY" -m desk.news status ;;
esac
