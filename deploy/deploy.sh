#!/usr/bin/env bash
#
# THE production deploy: GitHub main -> production, doing only what the commit needs.
#
#   git push origin main
#   bun run deploy
#
# 1. This checkout must be clean and exactly GitHub's main (fetched now): what is deployed is
#    what is on GitHub. GitHub CI is advisory and never waited for (`bun run status` shows it).
# 2. The commit is pushed to the production Git repository (/opt/aichat/app.git on the host).
# 3. On the host, deploy/server/update.sh (from this checkout's deploy/) moves the production
#    checkout /opt/aichat/app to the commit, rebuilds and restarts only the parts whose content
#    changed, and runs a local smoke check. It runs as a detached systemd unit, so a dropped
#    connection or Ctrl+C cannot stop it halfway; one deploy at a time (the host's lock).
# 4. It prints GitHub main, the production checkout, what the backend and the frontend run, and
#    MATCH or MISMATCH.
#
#   --host <user@host>   default root@10.1.50.94 (or $DEPLOY_HOST)
# Roll back: bun run rollback (deploy/rollback.sh). Docs: docs/deployment.md.
set -euo pipefail

CANONICAL=https://github.com/sunny436/AI-Tutor-Webapp-backend.git
PRODUCTION=10.1.50.94
HOST=${DEPLOY_HOST:-root@$PRODUCTION}
TARGET="" # set by deploy/rollback.sh: an earlier commit
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    --rollback-to) TARGET=${2:?--rollback-to needs a commit}; shift 2 ;;
    *) echo "unknown option: $1 (see the header of deploy/deploy.sh)" >&2; exit 2 ;;
  esac
done
stop() { echo "STOP: $*" >&2; exit 1; }

cd "$(git rev-parse --show-toplevel)"
. deploy/summary.sh
if [ "${DEPLOY_REHEARSAL:-0}" = 1 ]; then
  SOURCE=${DEPLOY_REHEARSAL_SOURCE:?DEPLOY_REHEARSAL needs DEPLOY_REHEARSAL_SOURCE (a local repository)}
  case "$HOST" in *"$PRODUCTION"*) stop "rehearsal mode never deploys to production ($HOST)" ;; esac
else
  SOURCE=$CANONICAL
fi
START=$(date +%s)
WORK=$(mktemp -d)
# One SSH connection for everything (falls back to separate ones where multiplexing is unavailable).
MUX=(-o ControlMaster=auto -o "ControlPath=$WORK/cm-%C" -o ControlPersist=60)
cleanup() { ssh "${MUX[@]}" -O exit "$HOST" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

# ---------------------------------------------------------------- 1. exactly GitHub's main
git fetch -q "$SOURCE" main 2> "$WORK/fetch" || stop "cannot fetch GitHub main ($(head -1 "$WORK/fetch"))"
MAIN=$(git rev-parse FETCH_HEAD)
if [ -z "$TARGET" ]; then
  [ -z "$(git status --porcelain --untracked-files=normal)" ] || stop "this checkout has uncommitted or untracked changes: commit, git push origin main, then deploy"
  HEAD_SHA=$(git rev-parse HEAD)
  [ "$HEAD_SHA" = "$MAIN" ] || stop "this checkout ($HEAD_SHA) is not GitHub main ($MAIN): git push origin main (or git pull), then deploy"
  SHA=$MAIN MODE=deploy
else
  SHA=$(git rev-parse --verify --quiet "$TARGET^{commit}") || stop "$TARGET is not a commit in this repository (git fetch origin)"
  MODE=rollback
fi
echo "==> $MODE $SHA  $(git log -1 --format=%s "$SHA")"

# ---------------------------------------------------------------- 2. production Git
INIT='test -d /opt/aichat/app.git || git init -q --bare /opt/aichat/app.git'
[ "${DEPLOY_REHEARSAL:-0}" = 1 ] && INIT="test -f /etc/aichat/REHEARSAL && $INIT"
ssh "${MUX[@]}" "$HOST" "$INIT" 2> /dev/null || { MUX=(); ssh "$HOST" "$INIT"; } || stop "cannot reach $HOST (or it is not a rehearsal host)"
GIT_SSH_COMMAND="ssh ${MUX[*]}" git push -q --force "ssh://$HOST/opt/aichat/app.git" "$SHA:refs/heads/main" \
  || stop "could not push $SHA to production Git"

# ---------------------------------------------------------------- 3. production
UNIT="aichat-deploy-${SHA:0:12}-$(date -u +%H%M%S)-$RANDOM"
OPERATOR=$(git config user.name 2> /dev/null | tr -cd 'A-Za-z0-9 ._-' | tr ' ' '_')
# The unit's whole journal is followed (its name is unique) up to update.sh's "@@END" line;
# "@@" lines are for this script, not the screen.
set +e
# shellcheck disable=SC2029  # expanded here on purpose
git archive --format=tar HEAD deploy | ssh "${MUX[@]}" "$HOST" "D=/run/$UNIT; rm -rf \$D && mkdir -p \$D && tar -xf - -C \$D || exit 1
journalctl -f -n all -o cat -u $UNIT | sed -u -n '/^@@END /q;p' &
systemd-run --unit=$UNIT --quiet --wait --collect -p Environment=HOME=/root -p Environment=AICHAT_MODE=$MODE -p Environment=AICHAT_OPERATOR=${OPERATOR:-unknown} -p \"Environment=AICHAT_SSH_CLIENT=\${SSH_CONNECTION// /,}\" bash \$D/deploy/server/update.sh $SHA
rc=\$?
for i in \$(seq 50); do pgrep -P \$\$ -x sed > /dev/null || break; sleep 0.1; done
pkill -P \$\$ > /dev/null 2>&1; rm -rf \$D; exit \$rc" | tee "$WORK/out" | grep --line-buffered -v '^@@'
RC=${PIPESTATUS[1]}
set -e

echo
print_summary "$MAIN" "$(grep '^@@STATUS ' "$WORK/out" | tail -1)"
echo "Time: $(($(date +%s) - START))s"
[ "$RC" = 0 ] || stop "the $MODE FAILED on $HOST (see above). Whatever was not restarted keeps serving; 'bun run rollback' returns to the previous commit."
[ "$MODE" = rollback ] || [ "$SUMMARY_MATCH" = 1 ] || stop "deployed, but production does not match GitHub main (see above)"
