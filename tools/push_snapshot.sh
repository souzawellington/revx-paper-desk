#!/usr/bin/env bash
# Envia o snapshot SIMULADO (só leitura, sanitizado) para a página online na Vercel.
#   tools/push_snapshot.sh            -> envia 1 vez (idempotente, com lock; seguro na rotina horária)
#   tools/push_snapshot.sh --ensure   -> garante que o ciclo de fundo (1×/min) está a correr; arranca-o se não estiver
#   tools/push_snapshot.sh --loop     -> ciclo em primeiro plano (usado pelo --ensure)
#   tools/push_snapshot.sh --stop | --status
#   --quiet                            -> sem saída (exceto erros) | --dry-run -> constrói e valida, não envia
# Cópia durável no Vercel Blob só a cada 30 min (X-Persist) para caber no plano grátis (2.000 escritas/mês).
# NUNCA passa chaves da Revolut ao processo (REVX_* removidas). O token de ingestão vai num ficheiro de cabeçalhos
# temporário (chmod 600), nunca na linha de comandos.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="${DASH_PY:-python3}"
RUN="$ROOT/logs/run"; mkdir -p "$RUN"
TOKF="${VERCEL_INGEST_TOKEN_FILE:-$ROOT/.vercel_ingest_token}"
URLF="$ROOT/desk/state/vercel_dashboard_url.txt"
URL="${VERCEL_DASH_URL:-$(head -1 "$URLF" 2>/dev/null)}"
EVERY="${PUSH_EVERY_S:-60}"; PERSIST_EVERY="${PERSIST_EVERY_S:-1800}"
MODE=once; QUIET=0; DRY=0
for a in "$@"; do case "$a" in --ensure) MODE=ensure;; --loop) MODE=loop;; --stop) MODE=stop;; --status) MODE=status;; --quiet) QUIET=1;; --dry-run) DRY=1;; esac; done
say(){ [ "$QUIET" = 1 ] || echo "$@"; }
alive(){ [ -f "$RUN/push.pid" ] && kill -0 "$(cat "$RUN/push.pid")" 2>/dev/null; }

once(){
  exec 9>"$RUN/push.lock"; flock -n 9 || { say "outro envio em curso"; return 0; }
  local snap="$RUN/snapshot.json" hdr code body persist=0 now last
  if ! env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH "$PY" -m bot.public_snapshot --out "$snap" 2>>"$ROOT/logs/push_snapshot.log"; then
    echo "ERRO: não consegui construir/validar o snapshot (ver logs/push_snapshot.log)" >&2; return 3; fi
  [ "$DRY" = 1 ] && { say "dry-run OK: $(wc -c <"$snap") bytes, sanitizado"; return 0; }
  [ -n "$URL" ] || { echo "ERRO: URL da página em falta ($URLF)" >&2; return 4; }
  [ -s "$TOKF" ] || { echo "ERRO: token de ingestão em falta ($TOKF)" >&2; return 4; }
  now=$(date +%s); last=$(cat "$RUN/push_last_persist" 2>/dev/null || echo 0)
  [ $((now - last)) -ge "$PERSIST_EVERY" ] && persist=1
  hdr="$(umask 077; mktemp "$RUN/.hdr.XXXXXX")"
  { printf 'Authorization: Bearer %s\n' "$(tr -d '\r\n' <"$TOKF")"; printf 'Content-Type: application/json\n'; printf 'X-Persist: %s\n' "$persist"; } >"$hdr"
  body="$RUN/push_resp.json"
  code=$(curl -sS -m 25 -o "$body" -w '%{http_code}' -X POST -H @"$hdr" --data-binary @"$snap" "${URL%/}/api/ingest" 2>>"$ROOT/logs/push_snapshot.log") || code=000
  rm -f "$hdr"
  printf '{"ts":%s,"http":"%s","persist_requested":%s,"resp":%s}\n' "$now" "$code" "$persist" "$(head -c 300 "$body" 2>/dev/null | tr -d '\n' | "$PY" -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" >"$RUN/push_status.json"
  if [ "$code" = 200 ]; then
    grep -q '"persisted":true' "$body" && echo "$now" >"$RUN/push_last_persist"
    say "enviado ($code) persist=$persist"; return 0
  fi
  echo "ERRO: envio falhou (HTTP $code) — ver logs/run/push_status.json" >&2; return 5
}

case "$MODE" in
  once) once; rc=$?; L="$ROOT/logs/push_snapshot.log"
        if [ -f "$L" ] && [ "$(stat -c %s "$L")" -gt 1048576 ]; then tail -n 2000 "$L" >"$L.tmp" && mv "$L.tmp" "$L"; fi
        exit $rc ;;
  loop) echo $$ >"$RUN/push.pid"; trap 'rm -f "$RUN/push.pid"; exit 0' INT TERM
        while true; do "$0" >>"$ROOT/logs/push_snapshot.log" 2>&1; sleep "$EVERY"; done ;;
  ensure) if alive; then say "ciclo de envio OK pid $(cat "$RUN/push.pid")"; else
            setsid nohup "$0" --loop >/dev/null 2>&1 < /dev/null & sleep 2
            if alive; then say "ciclo de envio (re)arrancado pid $(cat "$RUN/push.pid")"; else echo "ERRO: ciclo não arrancou" >&2; exit 6; fi
          fi ;;
  stop) if alive; then kill -TERM -- "-$(cat "$RUN/push.pid")" 2>/dev/null || kill "$(cat "$RUN/push.pid")"; rm -f "$RUN/push.pid"; say "parado"; else say "não estava a correr"; fi ;;
  status) alive && say "a correr pid $(cat "$RUN/push.pid")" || say "parado"; cat "$RUN/push_status.json" 2>/dev/null ;;
esac
