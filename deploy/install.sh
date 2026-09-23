#!/usr/bin/env bash
#
# Provision an Ubuntu 24.04 host for the chat stack (target configuration).
#
#   sudo bash deploy/install.sh
#
# Idempotent: installs what is missing, pulls what exists, re-renders units.
# It never writes secrets and never imports data. Secrets go in /etc/aichat/*.env
# (templates in deploy/env/); the script stops and lists any that are missing.
#
# NOT YET RUN IN PRODUCTION. Production cutover follows docs/production-migration.md
# and requires explicit approval.
set -euo pipefail

SLUG="aichat"
ROOT="/opt/$SLUG"
SECRETS_DIR="/etc/$SLUG"
BACKEND_REPO="${BACKEND_REPO:?set BACKEND_REPO to the git URL of the backend repository}"
FRONTEND_REPO="${FRONTEND_REPO:-}"   # optional until the frontend is migrated

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

log "1/6  packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates python3.12 python3.12-venv docker.io docker-compose-v2 >/dev/null
systemctl enable --now docker

log "2/6  code"
mkdir -p "$ROOT"
if [ -d "$ROOT/backend/.git" ]; then git -C "$ROOT/backend" pull --ff-only; else git clone "$BACKEND_REPO" "$ROOT/backend"; fi
if [ -n "$FRONTEND_REPO" ]; then
  if [ -d "$ROOT/frontend/.git" ]; then git -C "$ROOT/frontend" pull --ff-only; else git clone "$FRONTEND_REPO" "$ROOT/frontend"; fi
fi

log "3/6  secrets"
mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
missing=0
for f in postgres.env api.env; do
  if [ ! -s "$SECRETS_DIR/$f" ]; then echo "missing $SECRETS_DIR/$f (template: deploy/env/${f}.example)"; missing=1; fi
done
[ "$missing" -eq 0 ] || { echo "fill the files above, then re-run"; exit 1; }
chmod 600 "$SECRETS_DIR"/*.env

log "4/6  python environment"
cd "$ROOT/backend/backend-python"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

log "5/6  systemd units"
install -m 644 "$ROOT/backend/deploy/systemd/"$SLUG-*.service "$ROOT/backend/deploy/systemd/"$SLUG-*.timer /etc/systemd/system/
chmod 755 "$ROOT/backend/deploy/backup.sh"
systemctl daemon-reload
systemctl enable --now $SLUG-postgres.service $SLUG-api.service $SLUG-pg-backup.timer
# The web unit is enabled by hand once the frontend is migrated (docs/production-migration.md).

log "6/6  verify"
sleep 3
curl -fsS http://127.0.0.1:4000/ready && echo
bash "$ROOT/backend/deploy/infra-check.sh" || true
