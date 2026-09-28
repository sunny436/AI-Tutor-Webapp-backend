#!/usr/bin/env bash
#
# Roll production back: the web app AND the API return to the same earlier release together.
# There is no way to roll back one without the other. From the repository root:
#
#   bun run rollback                          undo the last switch (again: one release further back)
#   bun run rollback -- --to <commit>         to a specific kept release
#   bun run rollback -- --allow-older-schema  when the release being left migrated the schema
#   (--yes skips the typed confirmation; --host <user@host>, default root@10.1.30.37)
#
# Runs the live release's deploy/server/rollback.sh in a detached systemd unit, so a dropped
# connection cannot interrupt it. See docs/rollback.md.
set -euo pipefail
HOST=${DEPLOY_HOST:-root@10.1.30.37}
ARGS=() YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    --to) ARGS+=("$1" "${2:?--to needs a commit}"); shift 2 ;;
    --allow-older-schema) ARGS+=("$1"); shift ;;
    --yes) YES=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
LIVE=$(ssh "$HOST" 'r=$(readlink -e /opt/aichat/current 2>/dev/null) && case "$r" in /opt/aichat/releases/*) basename "$r" ;; esac' || true)
[ -n "$LIVE" ] || { echo "STOP: $HOST has no live release (/opt/aichat/current)" >&2; exit 1; }
echo "  Roll back $HOST from $LIVE (frontend and backend together) ${ARGS[*]:-to the previous release}"
if [ "$YES" != 1 ]; then
  read -r -p "  Type 'rollback' to continue: " answer
  [ "$answer" = rollback ] || { echo "STOP: not confirmed" >&2; exit 1; }
fi
UNIT="aichat-rollback-$(date -u +%Y%m%dT%H%M%S)"
# shellcheck disable=SC2029  # expanded here on purpose
ssh "$HOST" "journalctl -f -n0 -o cat -u $UNIT & J=\$!; systemd-run --unit=$UNIT --quiet --wait --collect -p Environment=HOME=/root -p Environment=AICHAT_VIA_DEPLOY=1 -p \"Environment=AICHAT_SSH_CLIENT=\${SSH_CONNECTION// /,}\" -p Environment=AICHAT_OPERATOR=$(git config user.name 2>/dev/null | tr -cd 'A-Za-z0-9 ._-' | tr ' ' '_') bash /opt/aichat/current/deploy/server/rollback.sh ${ARGS[*]:-}; rc=\$?; sleep 2; kill \$J 2>/dev/null; exit \$rc"
