#!/usr/bin/env bash
#
# Snapshot the self-hosted Convex deployment.
#
# A copy of the docker volume is NOT a substitute: it catches the database
# mid-write and may not restore. `convex export` produces a consistent snapshot
# that `convex import` accepts, and it includes file storage.
#
# Restore:
#   cd /opt/ayurveda/ayurveda-frontend/packages/backend
#   node ../../node_modules/convex/bin/main.js import --replace <archive.zip>
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/convex}"
KEEP_DAYS="${KEEP_DAYS:-30}"
CONVEX_CLI="/opt/ayurveda/ayurveda-frontend/node_modules/convex/bin/main.js"

mkdir -p "$BACKUP_DIR"
out="$BACKUP_DIR/convex-$(date +%Y-%m-%d-%H%M%S).zip"

# --include-file-storage is not the default. Without it you get the tables and
# none of the uploaded files - something you discover during a restore rather
# than during a backup.
node "$CONVEX_CLI" export --path "$out" --include-file-storage

# Fail loudly on an empty archive rather than reporting success and then
# rotating away the last good copy below.
if [ ! -s "$out" ]; then
  echo "backup: export produced no data at $out" >&2
  exit 1
fi
echo "backup: wrote $out ($(du -h "$out" | cut -f1))"

find "$BACKUP_DIR" -name 'convex-*.zip' -type f -mtime "+$KEEP_DAYS" -print -delete

# An off-box copy is what makes this a real backup. Archives sitting on the same
# disk as the database do not survive the failure they exist for. Point this at
# real storage and uncomment.
# rclone copy "$out" remote:ayurveda-convex/
