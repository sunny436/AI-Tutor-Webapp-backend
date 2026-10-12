#!/usr/bin/env bash
#
# Roll production back to an earlier commit, by the deploy's own path (deploy/deploy.sh): the
# commit is pushed to production Git, the checkout moves to it, and only the parts that differ
# are rebuilt or restarted. A frontend going back to the build the last deploy replaced is
# swapped back without building.
#
#   bun run rollback                  the commit that was live before the last deploy
#   bun run rollback -- <commit>      any earlier commit (see the host's HISTORY or git log)
#   (--host <user@host>, default root@10.1.50.94)
#
# The database is never rolled back: migrations are backward compatible (docs/deployment.md).
# Afterwards `bun run status` says MISMATCH (production is not GitHub main) until main is
# deployed again, usually with a fix.
set -euo pipefail
HOST=${DEPLOY_HOST:-root@10.1.50.94}
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) TARGET=$1; shift ;;
  esac
done
cd "$(git rev-parse --show-toplevel)"
if [ -z "$TARGET" ]; then
  TARGET=$(ssh "$HOST" 'cat /opt/aichat/app-state/previous 2>/dev/null' || true)
  [ -n "$TARGET" ] || { echo "STOP: $HOST has no previous deploy recorded; name a commit: bun run rollback -- <commit>" >&2; exit 1; }
fi
exec bash deploy/deploy.sh --host "$HOST" --rollback-to "$TARGET"
