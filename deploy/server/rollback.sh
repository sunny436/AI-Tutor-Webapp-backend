#!/usr/bin/env bash
#
# Roll production back to an earlier release: frontend AND backend together, because both run
# from the one directory /opt/aichat/current points at. Started by deploy/rollback.sh as a
# detached systemd unit (an SSH drop cannot interrupt it):
#
#   bash /opt/aichat/current/deploy/server/rollback.sh [--to <commit>] [--allow-older-schema]
#
# Without --to it undoes the last switch: the live-release stack is popped, so a second
# rollback goes one release further back, never forward again. The database is never rolled
# back; if the release being left migrated the schema, the older code must run on the newer
# schema, which is only safe for backward-compatible migrations: --allow-older-schema.
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
[ "${AICHAT_VIA_DEPLOY:-}" = 1 ] || die "roll back with 'bun run rollback' only; never run rollback.sh by hand"
[ "$(id -u)" -eq 0 ] || die "run as root"
exec 9>/run/aichat-deploy.lock
flock -n 9 || die "another deploy or rollback is running"

LIVE=$(current_release)
[ -n "$LIVE" ] || die "/opt/aichat/current does not point at a release"
mapfile -t STACK < <(live_stack)
if [ -z "$TARGET" ]; then
  [ "${#STACK[@]}" -ge 1 ] && [ "${STACK[-1]}" = "$LIVE" ] \
    || die "the live release $LIVE is not the top of $LIVE_STACK (was current changed by hand?); name the target with --to <commit>"
  [ "${#STACK[@]}" -ge 2 ] || die "no earlier release to roll back to"
  TARGET=${STACK[-2]}
  POP=1
else
  [[ "$TARGET" =~ ^[0-9a-f]{7,40}$ ]] || die "--to needs a commit (7 to 40 hex characters)"
  matches=()
  for dir in "$RELEASES/$TARGET"*; do [ -d "$dir" ] && is_commit "${dir##*/}" && matches+=("${dir##*/}"); done
  [ "${#matches[@]}" = 1 ] || die "release $TARGET not found (or ambiguous) in $RELEASES"
  TARGET=${matches[0]}
  POP=0
fi
[ "$TARGET" != "$LIVE" ] || die "$TARGET is already live"
[ -d "$RELEASES/$TARGET" ] || die "release $TARGET is no longer kept on this host; deploy it instead"
[ -f "$RELEASES/$TARGET/backend/.venv/.ready" ] && [ -f "$RELEASES/$TARGET/frontend/.ready" ] \
  || die "release $TARGET was never fully built; deploy it instead"

log "rollback: $LIVE -> $TARGET"
verify_release "$TARGET" || die "release $TARGET does not match its commit; deploy it instead"
status=$(migration_status "$TARGET")
known=$(json_field database_known <<<"$status")
database=$(json_field database <<<"$status")
pending=$(json_field pending <<<"$status")
if [ "$known" != True ]; then
  [ "$ALLOW_OLDER" = 1 ] || die "the database ($database) is newer than release $TARGET.
      Only continue if those migrations were backward compatible: re-run with --allow-older-schema."
  note "older code on a newer schema: allowed by --allow-older-schema"
fi
[ "$pending" = "[]" ] || die "release $TARGET expects migrations the database does not have ($pending)"

if activate "$TARGET"; then
  if [ "$POP" = 1 ]; then
    tmp=$(mktemp) && printf '%s\n' "${STACK[@]:0:${#STACK[@]}-1}" > "$tmp" && mv -f "$tmp" "$LIVE_STACK" \
      || note "(could not update $LIVE_STACK)"
  else
    push_live "$TARGET"
  fi
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
