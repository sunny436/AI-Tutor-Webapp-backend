#!/usr/bin/env bash
#
# Install the systemd units and the shared PostgreSQL files from a release directory.
# Called by release.sh before every switch and by install.sh on a new host. Idempotent.
#
#   bash deploy/server/install-units.sh /opt/aichat/releases/<commit>
#
# - Units point at /opt/aichat/current, so they are the same for every release; they are
#   only rewritten (and systemd reloaded) when their content changes.
# - The database is NOT part of app releases: its compose file lives in
#   /opt/aichat/shared/postgres and is installed once. A release with a different compose
#   file prints a warning instead of replacing it, because recreating the database container
#   must be a deliberate step. Project and volume names are pinned in that file, so its
#   location never changes which database volume is used.
# - Never restarts anything.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

SRC=${1:?usage: install-units.sh <release directory>}
[ "$(id -u)" -eq 0 ] || die "run as root"

SUFFIX=${BACKUP_SUFFIX:-.before-$(date -u +%Y%m%d%H%M%S)}  # replaced units are kept as <unit>$SUFFIX
changed=0
for unit in "$SRC"/deploy/systemd/aichat-*.service "$SRC"/deploy/systemd/aichat-*.timer; do
  target="/etc/systemd/system/$(basename "$unit")"
  if ! cmp -s "$unit" "$target"; then
    [ -f "$target" ] && cp -p "$target" "$target$SUFFIX"
    install -m 644 "$unit" "$target"
    note "updated $(basename "$unit")"
    changed=1
  fi
done
if [ "$changed" = 1 ]; then systemctl daemon-reload; fi
systemctl enable --quiet aichat-postgres.service aichat-pg-backup.timer
# The app units start at boot only once a release is live (a fresh host has none yet).
if [ -e "$CURRENT" ]; then systemctl enable --quiet aichat-api.service aichat-web.service; fi

install -d -m 755 "$SHARED/postgres"
compose="$SHARED/postgres/docker-compose.yml"
if [ ! -f "$compose" ]; then
  install -m 644 "$SRC/deploy/compose/docker-compose.yml" "$compose"
  note "installed $compose"
elif ! cmp -s "$SRC/deploy/compose/docker-compose.yml" "$compose"; then
  note "WARNING: this release's deploy/compose/docker-compose.yml differs from $compose."
  note "         The database container was left alone. To apply it deliberately, see docs/deployment.md."
fi
if ! cmp -s "$SRC/deploy/backup.sh" "$SHARED/postgres/backup.sh"; then
  install -m 755 "$SRC/deploy/backup.sh" "$SHARED/postgres/backup.sh"
  note "installed $SHARED/postgres/backup.sh"
fi
