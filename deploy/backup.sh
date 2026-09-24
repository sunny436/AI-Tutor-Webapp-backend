#!/usr/bin/env bash
#
# Nightly logical backup of the aichat PostgreSQL database (run by aichat-pg-backup.timer).
#
#   pg_dump custom format, compressed; restore with:
#   docker compose --env-file /etc/aichat/postgres.env -f /opt/aichat/shared/postgres/docker-compose.yml \
#     exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < <file>.dump
#
# A copy of the docker volume is not a backup: it can catch the database mid-write.
set -euo pipefail

: "${POSTGRES_USER:?}" "${POSTGRES_DB:?}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aichat}"
KEEP_DAYS="${KEEP_DAYS:-30}"
COMPOSE=(docker compose --env-file /etc/aichat/postgres.env -f /opt/aichat/shared/postgres/docker-compose.yml)

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
out="$BACKUP_DIR/aichat-$(date +%Y-%m-%d-%H%M%S).dump"

"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$out"

# Fail loudly on an empty dump rather than rotating away the last good copy.
if [ ! -s "$out" ]; then
  echo "backup: pg_dump produced no data at $out" >&2
  exit 1
fi
echo "backup: wrote $out ($(du -h "$out" | cut -f1))"
find "$BACKUP_DIR" -name 'aichat-*.dump' -type f -mtime "+$KEEP_DAYS" -print -delete

# Copy off the host for a real backup (a dump on the same disk does not survive the disk).
# rclone copy "$out" remote:aichat-backups/
