#!/usr/bin/env bash
#
# Provision an Ubuntu 24.04 host for the chat stack.
#
#   sudo BACKEND_REPO=<git url> FRONTEND_REPO=<git url> bash deploy/install.sh
#
# Idempotent: installs what is missing, pulls what exists, re-renders units.
# It never writes secrets and never imports data. Secrets go in /etc/aichat/*.env
# (templates in deploy/env/); the script stops and lists any that are missing.
#
# Safe to run on a host that still serves the legacy stack (docs/production-migration.md):
#   - an existing Docker installation is used as is: never replaced, upgraded or restarted;
#   - the API listens on 127.0.0.1:4100, beside the legacy API on :4000;
#   - it stops if :4100 or :5432 is held by anything other than our own units;
#   - the web app is built but not started: starting aichat-web.service is the switch-over,
#     because port 3000 is shared with the legacy web app.
set -euo pipefail

SLUG="aichat"
ROOT="/opt/$SLUG"
SECRETS_DIR="/etc/$SLUG"
API_PORT=4100
BUN_VERSION="1.3.14"   # the version the frontend's install, tests and build were verified with
BUN="/root/.bun/bin/bun"
BACKEND_REPO="${BACKEND_REPO:?set BACKEND_REPO to the git URL of the backend repository}"
FRONTEND_REPO="${FRONTEND_REPO:-}"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run as root"

# A port is usable when it is free or already served by our own unit.
require_port() {
  local port="$1" unit="$2"
  systemctl is-active --quiet "$unit" && return 0
  if ss -ltnH "( sport = :$port )" | grep -q .; then
    ss -ltnpH "( sport = :$port )" >&2
    die "port $port is in use by another process (above); $unit needs it"
  fi
}

clone_or_pull() {
  local repo="$1" dir="$2"
  if [ -d "$dir/.git" ]; then git -C "$dir" pull --ff-only; else git clone "$repo" "$dir"; fi
}

log "1/7  packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates unzip python3.12 python3.12-venv >/dev/null
if command -v docker >/dev/null 2>&1; then
  echo "docker already installed ($(docker --version)); leaving it untouched"
else
  apt-get install -y -qq docker.io docker-compose-v2 >/dev/null
  systemctl enable --now docker
fi
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is missing; install the compose plugin that matches this Docker"

log "2/7  ports"
require_port 5432 "$SLUG-postgres.service"
require_port "$API_PORT" "$SLUG-api.service"

log "3/7  code"
mkdir -p "$ROOT"
clone_or_pull "$BACKEND_REPO" "$ROOT/backend"
[ -z "$FRONTEND_REPO" ] || clone_or_pull "$FRONTEND_REPO" "$ROOT/frontend"

log "4/7  secrets"
mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
needed=(postgres.env api.env)
[ -z "$FRONTEND_REPO" ] || needed+=(web.env)
missing=0
for f in "${needed[@]}"; do
  if [ ! -s "$SECRETS_DIR/$f" ]; then echo "missing $SECRETS_DIR/$f (template: deploy/env/${f}.example)"; missing=1; fi
done
[ "$missing" -eq 0 ] || die "fill the files above, then re-run"
chmod 600 "$SECRETS_DIR"/*.env

log "5/7  API (python)"
cd "$ROOT/backend/backend-python"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

log "6/7  web app (build only)"
if [ -n "$FRONTEND_REPO" ]; then
  [ -x "$BUN" ] || curl -fsSL https://bun.sh/install | BUN_INSTALL=/root/.bun bash -s "bun-v$BUN_VERSION" >/dev/null
  # turbo looks up `bun` on PATH; sudo's secure_path and systemd do not include /root/.bun/bin.
  export PATH="$(dirname "$BUN"):$PATH"
  cd "$ROOT/frontend"
  export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
  "$BUN" install --frozen-lockfile
  # NEXT_PUBLIC_* values are inlined at build time, so build with the production env.
  (set -a; . "$SECRETS_DIR/web.env"; set +a; "$BUN" run build)
else
  echo "FRONTEND_REPO not set; skipping the web app"
fi

log "7/7  systemd units"
install -m 644 "$ROOT/backend/deploy/systemd/"$SLUG-*.service "$ROOT/backend/deploy/systemd/"$SLUG-*.timer /etc/systemd/system/
chmod 755 "$ROOT/backend/deploy/backup.sh"
systemctl daemon-reload
systemctl enable --now $SLUG-postgres.service $SLUG-pg-backup.timer
systemctl enable $SLUG-api.service
systemctl restart $SLUG-api.service   # picks up new code; in-flight replies are saved as cancelled
# aichat-web.service is installed but only enabled by hand at the switch-over
# (docs/production-migration.md). Once it is enabled, re-runs restart it onto the new build.
if systemctl is-enabled --quiet $SLUG-web.service 2>/dev/null; then systemctl restart $SLUG-web.service; fi

log "verify"
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$API_PORT/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "http://127.0.0.1:$API_PORT/ready" >/dev/null || die "API not ready; see: journalctl -u $SLUG-api -n 50"
echo "API ready on 127.0.0.1:$API_PORT"
bash "$ROOT/backend/deploy/infra-check.sh" || true
