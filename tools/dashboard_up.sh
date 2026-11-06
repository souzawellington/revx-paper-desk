#!/usr/bin/env bash
# Watchdog do painel SIMULADO (só leitura): (re)arranca dashboard (127.0.0.1:8050, Basic Auth) + túnel HTTPS
# cloudflared (quick tunnel, sem conta) se estiverem em baixo, e grava o URL público em desk/state/dashboard_url.txt.
# Idempotente: pode correr a cada hora numa rotina. Uso: tools/dashboard_up.sh [--restart] [--quiet]
# NUNCA passa chaves da Revolut ao dashboard (REVX_* removidas do ambiente).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="${DASH_PY:-python3}"; CF="${CLOUDFLARED:-cloudflared}"
PORT="${DASH_PORT:-8050}"; LOG="$ROOT/logs"; RUN="$LOG/run"; URLF="$ROOT/desk/state/dashboard_url.txt"
PWF="$ROOT/.dashboard_password"; QUIET=0; RESTART=0
for a in "$@"; do case "$a" in --restart) RESTART=1;; --quiet) QUIET=1;; esac; done
say(){ [ "$QUIET" = 1 ] || echo "$@"; }
mkdir -p "$LOG" "$RUN"
alive(){ [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
stop(){ if alive "$1"; then kill "$(cat "$1")" 2>/dev/null; sleep 1; fi; rm -f "$1"; }

if [ ! -s "$PWF" ]; then
  ( umask 077; "$PY" -c "import secrets;print(secrets.token_urlsafe(18))" > "$PWF" ); say "senha nova gerada em .dashboard_password"
fi
chmod 600 "$PWF"
if [ ! -x "$CF" ]; then
  mkdir -p "$(dirname "$CF")"
  curl -fsSL -o "$CF" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x "$CF"
fi
[ "$RESTART" = 1 ] && { stop "$RUN/dashboard.pid"; stop "$RUN/tunnel.pid"; }

# --- dashboard ---
if ! alive "$RUN/dashboard.pid" || ! curl -fsS -m 5 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  stop "$RUN/dashboard.pid"
  pkill -f "bot.dashboard --port $PORT" 2>/dev/null; sleep 1
  env -u REVX_API_KEY -u REVX_PRIVATE_KEY_PATH DASHBOARD_PASSWORD_FILE="$PWF" \
    nohup "$PY" -m bot.dashboard --port "$PORT" --host 127.0.0.1 --require-auth >>"$LOG/dashboard.log" 2>&1 &
  echo $! > "$RUN/dashboard.pid"
  for i in $(seq 1 20); do curl -fsS -m 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
  say "dashboard (re)arrancado pid $(cat "$RUN/dashboard.pid")"
else say "dashboard OK pid $(cat "$RUN/dashboard.pid")"; fi

# --- túnel ---  (DASH_TUNNEL=none: só local)
if [ "${DASH_TUNNEL:-cloudflared}" = none ]; then printf 'LOCAL_ONLY http://127.0.0.1:%s\n' "$PORT" > "$URLF"; say "só local: http://127.0.0.1:$PORT"; exit 0; fi
url(){ grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/tunnel.log" 2>/dev/null | tail -1; }
need=0
if ! alive "$RUN/tunnel.pid"; then need=1
else
  U="$(url)"
  if [ -z "$U" ]; then need=1
  else
    ok=0; for i in 1 2 3; do curl -fsS -m 10 "$U/healthz" >/dev/null 2>&1 && { ok=1; break; }; sleep 3; done
    [ "$ok" = 1 ] || need=1
  fi
fi
if [ "$need" = 1 ]; then
  stop "$RUN/tunnel.pid"; pkill -f "cloudflared tunnel .*--url http://127.0.0.1:$PORT" 2>/dev/null; sleep 1
  : > "$LOG/tunnel.log"
  nohup "$CF" tunnel --no-autoupdate --protocol http2 --url "http://127.0.0.1:$PORT" >>"$LOG/tunnel.log" 2>&1 &
  echo $! > "$RUN/tunnel.pid"
  for i in $(seq 1 40); do [ -n "$(url)" ] && break; sleep 1; done
  U="$(url)"
  reg=0; for i in $(seq 1 30); do grep -q "Registered tunnel connection" "$LOG/tunnel.log" && { reg=1; break; }; sleep 1; done
  if [ "$reg" != 1 ]; then
    stop "$RUN/tunnel.pid"
    printf 'TUNNEL_BLOCKED %s: cloudflared não conseguiu ligar ao edge (porta 7844/QUIC bloqueada na rede desta box). Painel só em http://127.0.0.1:%s\n' "$(date -Is)" "$PORT" > "$URLF"
    say "TUNNEL_BLOCKED: a rede da box não deixa o cloudflared ligar ao edge (ver logs/tunnel.log). Dashboard local continua em http://127.0.0.1:$PORT"
    exit 2
  fi
  for i in $(seq 1 30); do curl -fsS -m 5 "$U/healthz" >/dev/null 2>&1 && break; sleep 2; done
  say "túnel (re)arrancado pid $(cat "$RUN/tunnel.pid") — URL NOVO"
else say "túnel OK pid $(cat "$RUN/tunnel.pid")"; fi
U="$(url)"
if [ -n "$U" ]; then
  PREV="$(cat "$URLF" 2>/dev/null | head -1)"
  printf '%s\n' "$U" > "$URLF"
  [ "$PREV" != "$U" ] && say "URL_CHANGED"
  say "URL: $U"
else say "ERRO: túnel sem URL (ver logs/tunnel.log)"; exit 1; fi
