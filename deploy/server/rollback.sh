#!/usr/bin/env bash
#
# Roll production back to an earlier release: frontend AND backend together, because both run
# from the one directory that /opt/aichat/current points at. Started by deploy/rollback.sh.
#
#   bash /opt/aichat/current/deploy/server/rollback.sh [--to <commit>] [--allow-older-schema]
#
# Without --to it returns to the release that was live before the current one. The database is
# never rolled back. If the current release migrated the schema, the older code runs on the
# newer schema, which is only safe for backward-compatible migrations, so that case needs
# --allow-older-schema.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

TARGET="" ALLOW_OLDER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --to) TARGET=${2:?--to needs a commit}; shift 2 ;;
    --allow-older-schema) ALLOW_OLDER=1; shift ;;
    *) die "unknown option $1" ;;
  esac
done
[ "$(id -u)" -eq 0 ] || die "run as root"
exec 9>/run/aichat-deploy.lock
flock -n 9 || die "another deploy or rollback is running"

LIVE=$(current_release)
[ -n "$LIVE" ] || die "/opt/aichat/current does not point at a release"
if [ -z "$TARGET" ]; then
  # The most recent release that was live before this one, from the deploy history.
  TARGET=$(grep -oE '^[^ ]+ deployed [0-9a-f]{40}' "$HISTORY" 2>/dev/null | awk '{print $3}' \
    | grep -v "^$LIVE$" | tail -1 || true)
  [ -n "$TARGET" ] || die "no earlier release in $HISTORY; name one with --to <commit>"
fi
case "$TARGET" in ???????*) ;; *) die "give a full or 7+ character commit" ;; esac
matches=()
for dir in "$RELEASES/$TARGET"*; do [ -d "$dir" ] && matches+=("${dir##*/}"); done
[ "${#matches[@]}" = 1 ] || die "release $TARGET not found (or ambiguous) in $RELEASES"
TARGET=${matches[0]}
[ "$TARGET" != "$LIVE" ] || die "$TARGET is already live"
[ -f "$RELEASES/$TARGET/backend/.venv/.ready" ] && [ -f "$RELEASES/$TARGET/frontend/.ready" ] \
  || die "release $TARGET was never fully built; deploy it instead"

log "rollback: $LIVE -> $TARGET"
status=$(migration_status "$TARGET")
if [ "$(json_field database_known <<<"$status")" != True ]; then
  [ "$ALLOW_OLDER" = 1 ] || die "the database ($(json_field database <<<"$status")) is newer than release $TARGET.
      Only continue if those migrations were backward compatible: re-run with --allow-older-schema."
  note "older code on a newer schema: allowed by --allow-older-schema"
fi
pending=$(json_field pending <<<"$status")
[ "$pending" = "[]" ] || die "release $TARGET expects migrations the database does not have ($pending)"

if activate "$TARGET"; then
  record "rolled back $LIVE -> $TARGET"
  log "live: $TARGET (was $LIVE)"
  exit 0
fi
note "live checks FAILED on $TARGET; returning to $LIVE"
if activate "$LIVE"; then
  record "rollback $LIVE -> $TARGET FAILED; stayed on $LIVE"
  die "rollback failed its checks; production is back on $LIVE"
fi
record "rollback $LIVE -> $TARGET FAILED and return to $LIVE FAILED"
die "production is unhealthy: investigate now (journalctl -u aichat-api -u aichat-web)"
