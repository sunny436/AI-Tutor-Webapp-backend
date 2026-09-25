#!/usr/bin/env bash
#
# What is running in production, and proof that frontend and backend run the SAME release:
#
#   bun run status        (read-only; exits 1 unless "INVARIANT OK")
#
# Sends this checkout's deploy/server/status.sh over ssh, so it also works on a host that does
# not run the release layout yet. --host <user@host>, default root@10.1.30.37 (or $DEPLOY_HOST).
set -euo pipefail
HOST=${DEPLOY_HOST:-root@10.1.30.37}
[ "${1:-}" = --host ] && HOST=${2:?--host needs a value}
cd "$(git rev-parse --show-toplevel)"
ssh "$HOST" 'bash -s' < deploy/server/status.sh
