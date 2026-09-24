# shellcheck shell=bash
# shellcheck disable=SC2034  # the constants are used by the scripts that source this file
# Shared helpers for deploy/server/release.sh, rollback.sh, install-units.sh, infra-check.sh
# and install.sh. Sourced, never run.
# Runs on the production host as root. Never prints secret values.

ROOT=/opt/aichat
RELEASES="$ROOT/releases"
CURRENT="$ROOT/current"
SHARED="$ROOT/shared"
SECRETS=/etc/aichat
HISTORY="$RELEASES/HISTORY"
BUN=/root/.bun/bin/bun
API_PORT=4100
WEB_PORT=3000

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }

# The release a path belongs to (the <commit> directory name), or empty.
release_of() {
  local path
  path=$(readlink -f "$1" 2>/dev/null) || return 0
  case "$path" in "$RELEASES"/*) path=${path#"$RELEASES"/}; printf '%s' "${path%%/*}" ;; esac
}

current_release() { release_of "$CURRENT"; }

# Wait until a URL answers with a 2xx/3xx status.
wait_http() {
  local url=$1 seconds=${2:-60} i
  for ((i = 0; i < seconds; i++)); do
    curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

# Prove browser -> web -> API -> database on a web port: a request with a made-up session
# must travel through the BFF to the API (which looks the session up in PostgreSQL) and
# come back 401, and the API's own log must show the same request id.
check_chain() {
  local port=$1 api_unit=$2 headers body status rid i
  headers=$(mktemp) body=$(mktemp)
  status=$(curl -s -o "$body" -D "$headers" -w '%{http_code}' --max-time 20 \
    -H "Cookie: aichat_session=deploy-chain-check" "http://127.0.0.1:$port/api/v1/conversations" || true)
  rid=$(grep -i '^x-request-id:' "$headers" | tr -d '\r' | awk '{print $2}')
  if [ "$status" != 401 ] || ! grep -q '"unauthorized"' "$body" || [ -z "$rid" ]; then
    rm -f "$headers" "$body"
    note "chain check: expected 401 unauthorized with a request id, got HTTP $status"
    return 1
  fi
  rm -f "$headers" "$body"
  for ((i = 0; i < 10; i++)); do
    if journalctl -u "$api_unit" --since "-5 min" -o cat --no-pager 2>/dev/null | grep -q "$rid"; then
      note "chain ok: web :$port -> $api_unit -> database (request $rid)"
      return 0
    fi
    sleep 1
  done
  note "chain check: request $rid never reached $api_unit"
  return 1
}

# Both running services must execute from the same release directory.
same_release() {
  local want=$1 unit pid got
  for unit in aichat-api aichat-web; do
    pid=$(systemctl show -p MainPID --value "$unit")
    [ -n "$pid" ] && [ "$pid" != 0 ] || { note "$unit is not running"; return 1; }
    got=$(release_of "/proc/$pid/cwd")
    [ "$got" = "$want" ] || { note "$unit runs release '${got:-unknown}', expected $want"; return 1; }
  done
  note "aichat-api and aichat-web both run release $want"
}

# Migration status of a release's code against the production database (JSON line).
migration_status() {
  local rel=$1
  systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
    -p WorkingDirectory="$RELEASES/$rel/backend" \
    "$RELEASES/$rel/backend/.venv/bin/python" scripts/migration_status.py
}

json_field() { python3 -c "import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])" "$1"; }

# Point `current` at a release atomically, then restart the API and the web app on it.
activate() {
  local rel=$1
  ln -sfn "$RELEASES/$rel" "$ROOT/current.next"
  mv -Tf "$ROOT/current.next" "$CURRENT"
  systemctl restart aichat-api
  wait_http "http://127.0.0.1:$API_PORT/ready" 60 || { note "API not ready on :$API_PORT"; return 1; }
  systemctl restart aichat-web
  wait_http "http://127.0.0.1:$WEB_PORT/login" 90 || { note "web app not answering on :$WEB_PORT"; return 1; }
  check_chain "$WEB_PORT" aichat-api && same_release "$rel"
}

record() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$HISTORY"; }
