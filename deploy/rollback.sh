#!/usr/bin/env bash
#
# Roll production back, frontend and backend together. From the repository root:
#
#   bun run rollback                          # to the release that was live before this one
#   bun run rollback -- --to <commit>         # to a specific kept release
#   bash deploy/rollback.sh --allow-older-schema
#
# Runs deploy/server/rollback.sh of the release that is live now. See docs/rollback.md.
set -euo pipefail
HOST=${DEPLOY_HOST:-root@10.1.30.37}
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    --to) ARGS+=("$1" "${2:?--to needs a commit}"); shift 2 ;;
    --allow-older-schema) ARGS+=("$1"); shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
ssh "$HOST" bash /opt/aichat/current/deploy/server/rollback.sh "${ARGS[@]}"
