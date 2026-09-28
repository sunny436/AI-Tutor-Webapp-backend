#!/usr/bin/env bash
#
# What is running in production, and proof that frontend and backend run the SAME release:
#
#   bun run status        (read-only; exits 1 unless "INVARIANT OK")
#
# Sends this checkout's deploy/server/status.sh over ssh, so it also works on a host that does
# not run the release layout yet. --host <user@host>, default root@10.1.30.37 (or $DEPLOY_HOST).
# Then, from here: how the live release relates to GitHub's main (merged? ahead? rolled back?)
# and GitHub CI's verdict on it. Both are information, never part of the invariant: production
# does not depend on GitHub, but it should not drift from it unnoticed.
set -uo pipefail
HOST=${DEPLOY_HOST:-root@10.1.30.37}
[ "${1:-}" = --host ] && HOST=${2:?--host needs a value}
cd "$(git rev-parse --show-toplevel)" || exit 1
ssh "$HOST" 'bash -s' < deploy/server/status.sh
RC=$?

SOURCE=https://github.com/sunny436/AI-Tutor-Webapp-backend.git
[ "${DEPLOY_REHEARSAL:-0}" = 1 ] && SOURCE=${DEPLOY_REHEARSAL_SOURCE:?}
echo "github"
LIVE=$(ssh "$HOST" 'r=$(readlink -e /opt/aichat/current 2>/dev/null) && case "$r" in /opt/aichat/releases/*) basename "$r" ;; esac' 2>/dev/null)
if [ -z "$LIVE" ]; then
  echo "  info  no live release"
elif ! git fetch --quiet --prune "$SOURCE" "+refs/heads/*:refs/deploy/heads/*" 2>/dev/null; then
  echo "  info  $SOURCE unreachable: cannot compare the live release with GitHub"
else
  MAIN=$(git rev-parse --verify --quiet refs/deploy/heads/main)
  ON=$(git for-each-ref --contains "$LIVE" --format='%(refname)' refs/deploy/heads 2>/dev/null | sed 's#^refs/deploy/heads/##' | paste -sd' ' -)
  if [ -z "$ON" ]; then
    echo "  WARN  the live release ${LIVE:0:12} is on no branch of GitHub: push it (the code in production must be on GitHub)"
  elif [ "$LIVE" = "$MAIN" ]; then
    echo "  ok    GitHub main == the live release"
  elif git merge-base --is-ancestor "$MAIN" "$LIVE"; then
    echo "  WARN  the live release is $(git rev-list --count "$MAIN..$LIVE") commit(s) ahead of GitHub main (on: $ON): merge it into main"
  elif git merge-base --is-ancestor "$LIVE" "$MAIN"; then
    echo "  WARN  GitHub main is $(git rev-list --count "$LIVE..$MAIN") commit(s) ahead of the live release: deploy it (or production was rolled back on purpose)"
  else
    echo "  WARN  the live release and GitHub main have diverged: merge the live release into main before the next deploy"
  fi
  if [ "${DEPLOY_REHEARSAL:-0}" = 1 ]; then
    echo "  info  GitHub CI: not in a rehearsal"
  else
    CI=$(bun deploy/ci-gate.mjs --report "$LIVE" 2>/dev/null)
    case "$CI" in
      FAILURE*) echo "  WARN  GitHub CI on the live release: $CI (look at it; 'bun run rollback' if it is real)" ;;
      *) echo "  info  GitHub CI on the live release: ${CI:-unavailable}" ;;
    esac
  fi
fi
exit "$RC"
