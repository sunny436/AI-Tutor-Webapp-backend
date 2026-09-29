#!/usr/bin/env bash
#
# Prepare an Ubuntu 24.04 host for the application. Run once per host (and again to repair it),
# from any copy of this repository, for example an extracted release:
#
#   sudo bash deploy/install.sh
#
# Installs system packages (git included) and Bun, creates /opt/aichat/{app-state,shared,runtime},
# checks that the secret files exist, installs the systemd units and the shared PostgreSQL files,
# and starts PostgreSQL and the backup timer. It never builds or starts the app (the first
# `bun run deploy` does), never writes secrets and never imports data.
#
# Safe on a host that runs other services: an existing Docker installation is used as is
# (never replaced, upgraded or restarted), and it stops if :5432 is held by anything other
# than our own database unit.
set -euo pipefail
SRC=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
. "$SRC/deploy/server/lib.sh"
BUN_VERSION=$(tr -d '[:space:]' < "$SRC/.bun-version")   # one pinned version everywhere (CI reads the same file)

[ "$(id -u)" -eq 0 ] || die "run as root"

log "1/5 packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates unzip xz-utils git python3.12 python3.12-venv >/dev/null
# OCR for students' scanned PDFs and photos (app/files/extract.py), English and Hindi.
apt-get install -y -qq tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin >/dev/null
if command -v docker >/dev/null 2>&1; then
  note "docker already installed ($(docker --version)); leaving it untouched"
else
  apt-get install -y -qq docker.io docker-compose-v2 >/dev/null
  systemctl enable --now docker
fi
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is missing; install the compose plugin that matches this Docker"

log "2/5 bun $BUN_VERSION"
if [ ! -x "$BUN" ] || [ "$("$BUN" --version)" != "$BUN_VERSION" ]; then
  curl -fsSL https://bun.sh/install | BUN_INSTALL=/root/.bun bash -s "bun-v$BUN_VERSION" >/dev/null
fi
[ "$("$BUN" --version)" = "$BUN_VERSION" ] || die "bun $BUN_VERSION could not be installed"

log "3/5 directories and the pinned Node runtime"
install -d -m 755 "$STATE" "$SHARED" "$RUNTIMES"
ensure_node "$SRC"
note "Node $(tr -d '[:space:]' < "$SRC/.node-version") ready in $RUNTIMES"

log "4/5 secrets"
install -d -m 700 "$SECRETS"
missing=0
for f in postgres.env api.env web.env; do
  if [ ! -s "$SECRETS/$f" ]; then note "missing $SECRETS/$f (template: deploy/env/$f.example)"; missing=1; fi
done
[ "$missing" -eq 0 ] || die "fill the files above (docs/deployment.md), then re-run"
chmod 600 "$SECRETS"/*.env

log "5/5 units and database"
if ! systemctl is-active --quiet aichat-postgres.service && ss -ltnH "( sport = :5432 )" | grep . >/dev/null; then
  ss -ltnpH "( sport = :5432 )" >&2
  die "port 5432 is in use by another process (above); aichat-postgres needs it"
fi
bash "$SRC/deploy/server/install-units.sh" "$SRC"
systemctl enable --now aichat-postgres.service aichat-pg-backup.timer
note "PostgreSQL and the nightly backup are running."
log "host ready. From a workstation: git push origin main && bun run deploy (docs/deployment.md)"
