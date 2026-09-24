# shellcheck shell=bash
# shellcheck disable=SC2034  # the constants are used by the scripts that source this file
# Shared helpers for deploy/server/release.sh, rollback.sh, install-units.sh, infra-check.sh
# and install.sh. Sourced, never run. Runs on the production host as root.
# Never prints secret values.
#
# The invariant every function here protects: the web app and the API always run the SAME
# release (one commit), from /opt/aichat/current -> /opt/aichat/releases/<commit>.

ROOT=/opt/aichat
RELEASES="$ROOT/releases"
CURRENT="$ROOT/current"
SHARED="$ROOT/shared"
SECRETS=/etc/aichat
HISTORY="$RELEASES/HISTORY"
LIVE_STACK="$RELEASES/LIVE-STACK"   # releases made live, oldest first; rollback pops it
BUN=/root/.bun/bin/bun
API_PORT=4100
WEB_PORT=3000
HERE=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")

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

is_commit() { [[ "$1" =~ ^[0-9a-f]{40}$ ]]; }

# Wait until a URL answers with a 2xx/3xx status.
wait_http() {
  local url=$1 seconds=${2:-60} i
  for ((i = 0; i < seconds; i++)); do
    curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

# The release a running app reports on its health endpoint ("" if it does not answer).
reported_release() {
  curl -fsS --max-time 5 "$1" 2>/dev/null \
    | python3.12 -c 'import json,sys; print(json.load(sys.stdin).get("release", ""))' 2>/dev/null || true
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

# Every process of a unit (not just its main process) must run from release $2.
unit_runs_release() {
  local unit=$1 want=$2 cgroup pid got count=0
  cgroup=$(systemctl show -p ControlGroup --value "$unit")
  [ -n "$cgroup" ] && [ -r "/sys/fs/cgroup$cgroup/cgroup.procs" ] || { note "$unit is not running"; return 1; }
  while read -r pid; do
    [ -n "$pid" ] || continue
    got=$(release_of "/proc/$pid/cwd")
    [ "$got" = "$want" ] || { note "$unit process $pid runs '${got:-outside any release}', expected $want"; return 1; }
    count=$((count + 1))
  done < "/sys/fs/cgroup$cgroup/cgroup.procs"
  [ "$count" -gt 0 ] || { note "$unit has no processes"; return 1; }
}

# THE invariant: pointer == API-reported release == web-reported release == the release every
# API and web process runs from.
same_release() {
  local want=$1 api web
  [ "$(current_release)" = "$want" ] || { note "/opt/aichat/current is not $want"; return 1; }
  unit_runs_release aichat-api "$want" && unit_runs_release aichat-web "$want" || return 1
  api=$(reported_release "http://127.0.0.1:$API_PORT/health")
  web=$(reported_release "http://127.0.0.1:$WEB_PORT/api/health")
  [ "$api" = "$want" ] || { note "the API reports release '${api:-none}', expected $want"; return 1; }
  [ "$web" = "$want" ] || { note "the web app reports release '${web:-none}', expected $want"; return 1; }
  note "invariant ok: pointer = API = web = every process = $want"
}

# Migration status of a release's code against the production database (JSON line).
migration_status() {
  local rel=$1
  systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
    -p WorkingDirectory="$RELEASES/$rel/backend" \
    "$RELEASES/$rel/backend/.venv/bin/python" scripts/migration_status.py
}

json_field() { python3.12 -c "import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])" "$1"; }

# The release's files must be exactly its commit (MANIFEST = `git ls-tree -r -z` of the commit).
verify_release() {
  local rel=$1
  [ -f "$RELEASES/$rel/MANIFEST" ] || { note "release $rel has no MANIFEST"; return 1; }
  python3.12 "$HERE/verify-release.py" "$RELEASES/$rel"
}

# Enough disk and memory to build a release without starving production or PostgreSQL.
preflight_resources() {
  local free_mb avail_mb min_free=${AICHAT_MIN_FREE_MB:-5000} min_mem=${AICHAT_MIN_MEMORY_MB:-1500}
  free_mb=$(df -Pm "$ROOT" | awk 'NR==2 {print $4}')
  avail_mb=$(awk '/^MemAvailable:|^SwapFree:/ {sum += $2} END {print int(sum / 1024)}' /proc/meminfo)
  [ "$free_mb" -ge "$min_free" ] || die "only ${free_mb} MB free on $ROOT (need ${min_free} MB); the database shares this disk"
  [ "$avail_mb" -ge "$min_mem" ] || die "only ${avail_mb} MB memory+swap available (need ${min_mem} MB)"
  note "resources ok: ${free_mb} MB disk, ${avail_mb} MB memory+swap available"
}

# The Node runtime a release is built, validated and served with: the release's own
# .node-version (the same file CI's setup-node reads). Each version is installed once from
# nodejs.org, verified against the published SHA-256 list, into /opt/aichat/runtime.
RUNTIMES="$ROOT/runtime"
node_bin_of() { printf '%s/node-v%s-linux-x64/bin' "$RUNTIMES" "$(tr -d '[:space:]' < "$1/.node-version")"; }
ensure_node() {
  local release_dir=$1 version tarball tmp
  version=$(tr -d '[:space:]' < "$release_dir/.node-version")
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "invalid .node-version in $release_dir: '$version'"
  [ -x "$RUNTIMES/node-v$version-linux-x64/bin/node" ] && return 0
  tarball="node-v$version-linux-x64.tar.xz"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/$tarball" "https://nodejs.org/dist/v$version/$tarball" || die "could not download Node $version"
  curl -fsSL -o "$tmp/SHASUMS256.txt" "https://nodejs.org/dist/v$version/SHASUMS256.txt" || die "could not download Node's checksums"
  (cd "$tmp" && grep -E " $tarball\$" SHASUMS256.txt | sha256sum -c --status) || die "Node $version failed its SHA-256 check"
  mkdir -p "$RUNTIMES" && tar -xJf "$tmp/$tarball" -C "$tmp" && mv "$tmp/node-v$version-linux-x64" "$RUNTIMES/"
  rm -rf "$tmp"
  note "installed Node $version (checksum verified)"
}

# Run a build step capped in memory and at low priority, so the kernel kills the build,
# never the live services or PostgreSQL.
build_step() {
  systemd-run --scope --quiet --nice=10 -p MemoryMax="${AICHAT_BUILD_MEMORY_MAX:-2G}" -- "$@"
}

# Switch production to a release. Order matters: the web app is stopped BEFORE the pointer
# moves and started AFTER the API runs the new release, so an old web app never serves
# against a new API (or the reverse). Users see the site unavailable for those seconds.
activate() {
  local rel=$1
  BACKUP_SUFFIX=${STAMP:-.before-$(date -u +%Y%m%d%H%M%S)} \
    bash "$RELEASES/$rel/deploy/server/install-units.sh" "$RELEASES/$rel" \
    || { note "could not install the units of $rel"; return 1; }
  systemctl reset-failed aichat-api aichat-web >/dev/null 2>&1 || true
  systemctl stop aichat-web
  ln -sfn "$RELEASES/$rel" "$ROOT/current.next"
  mv -Tf "$ROOT/current.next" "$CURRENT"
  systemctl restart aichat-api
  wait_http "http://127.0.0.1:$API_PORT/ready" 90 || { note "API not ready on :$API_PORT"; return 1; }
  systemctl start aichat-web
  wait_http "http://127.0.0.1:$WEB_PORT/login" 120 || { note "web app not answering on :$WEB_PORT"; return 1; }
  check_chain "$WEB_PORT" aichat-api && same_release "$rel"
}

# Bookkeeping never turns a finished switch into a reported failure.
record() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$HISTORY" 2>/dev/null || note "(could not write $HISTORY)"; }
push_live() { printf '%s\n' "$1" >> "$LIVE_STACK" 2>/dev/null || note "(could not write $LIVE_STACK)"; }
live_stack() { [ -f "$LIVE_STACK" ] && grep -E '^[0-9a-f]{40}$' "$LIVE_STACK" || true; }
