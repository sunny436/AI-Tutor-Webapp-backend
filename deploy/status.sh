#!/usr/bin/env bash
#
# What production runs, compared with GitHub main. Read-only:
#
#   bun run status        (exits 1 unless everything is healthy and "Status: MATCH")
#
# Runs deploy/server/status.sh on the host over ssh (units, health, what each part runs, the
# public URL, the last deploys), then prints GitHub main, the production checkout, the commit
# the backend and the frontend run, and MATCH or MISMATCH. GitHub CI's verdict on the checkout
# is shown as information only. --host <user@host>, default root@10.1.50.94 (or $DEPLOY_HOST).
set -uo pipefail
HOST=${DEPLOY_HOST:-root@10.1.50.94}
[ "${1:-}" = --host ] && HOST=${2:?--host needs a value}
cd "$(git rev-parse --show-toplevel)" || exit 1
. deploy/summary.sh
SOURCE=https://github.com/sunny436/AI-Tutor-Webapp-backend.git
[ "${DEPLOY_REHEARSAL:-0}" = 1 ] && SOURCE=${DEPLOY_REHEARSAL_SOURCE:?}

OUT=$(cat deploy/server/lib.sh deploy/server/status.sh | ssh "$HOST" 'bash -s')
RC=$?
printf '%s\n' "$OUT" | grep -v '^@@'
MAIN=""
git fetch -q "$SOURCE" main 2> /dev/null && MAIN=$(git rev-parse FETCH_HEAD)
echo
print_summary "$MAIN" "$(printf '%s\n' "$OUT" | grep '^@@STATUS ' | tail -1)"
CHECKOUT=$(printf '%s\n' "$OUT" | sed -n 's/^@@STATUS checkout=\([0-9a-f]*\).*/\1/p' | tail -1)
if [ -n "$CHECKOUT" ] && [ "${DEPLOY_REHEARSAL:-0}" != 1 ]; then
  echo "GitHub CI (advisory): $(timeout 20 bun deploy/ci-gate.mjs --report "$CHECKOUT" 2> /dev/null || echo unavailable)"
fi
[ "$RC" = 0 ] && [ "$SUMMARY_MATCH" = 1 ]
