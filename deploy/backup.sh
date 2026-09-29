#!/usr/bin/env bash
#
# Nightly logical backup of the aichat PostgreSQL database (run by aichat-pg-backup.timer).
#
#   pg_dump custom format, compressed; restore with:
#   docker compose --env-file /etc/aichat/postgres.env -f /opt/aichat/shared/postgres/docker-compose.yml \
#     exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < <file>.dump
#
# file_chunks (the text and embeddings of students' files) is derived data and is not dumped:
# the files themselves are. After a restore, have every ready file read again (the API does it):
#   ... exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
#     "UPDATE user_files SET status='processing', attempts=0, error_code=NULL WHERE status='ready'"
#
# A copy of the docker volume is not a backup: it can catch the database mid-write.
set -euo pipefail

: "${POSTGRES_USER:?}" "${POSTGRES_DB:?}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aichat}"
KEEP_DAYS="${KEEP_DAYS:-7}"
COMPOSE=(docker compose --env-file /etc/aichat/postgres.env -f /opt/aichat/shared/postgres/docker-compose.yml)

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
out="$BACKUP_DIR/aichat-$(date +%Y-%m-%d-%H%M%S).dump"

# The dumps share the database's disk: never write one that could fill it (a full disk stops
# PostgreSQL). Refuse, loudly, when less than twice the database's size is free.
db_bytes=$("${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT pg_database_size(current_database())" | tr -dc '0-9')
free_bytes=$(df --output=avail -B1 "$BACKUP_DIR" | tail -1 | tr -dc '0-9')
if [ -n "$db_bytes" ] && [ -n "$free_bytes" ] && [ "$free_bytes" -lt $((2 * db_bytes)) ]; then
  echo "backup: only $free_bytes bytes free for a $db_bytes-byte database; not dumping (free disk space first)" >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
  --exclude-table-data=file_chunks > "$out"

# Fail loudly on an empty dump rather than rotating away the last good copy.
if [ ! -s "$out" ]; then
  echo "backup: pg_dump produced no data at $out" >&2
  exit 1
fi
echo "backup: wrote $out ($(du -h "$out" | cut -f1))"
find "$BACKUP_DIR" -name 'aichat-*.dump' -type f -mtime "+$KEEP_DAYS" -print -delete

# Copy off the host for a real backup (a dump on the same disk does not survive the disk).
# rclone copy "$out" remote:aichat-backups/
