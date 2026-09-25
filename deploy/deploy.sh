#!/usr/bin/env bash
#
# THE production deployment command. AI Tutor is released as one application: one commit of
# main -> one release (frontend + backend together) -> production. There is no other way.
#
#   bun run deploy                          the tip of GitHub's main (the normal case)
#   bun run deploy -- --with-migrations     the release has pending database migrations
#   bun run deploy -- --prepare-only        build + validate on the host, do not switch
#   bun run deploy -- --ref <commit> --older   an OLDER commit of main (prefer `bun run rollback`)
#
#   --allow-older-schema   deploy code older than the database schema (backward-compatible only)
#   --yes                  skip the typed confirmation (automation)
#   --host <user@host>     default: root@10.1.30.37 (or $DEPLOY_HOST)
#
# Checked here, before anything is sent: the commit comes from GitHub's main (fetched from the
# pinned repository URL, never from a local branch), it is a commit OF main (not a commit merged
# into it), and CI passed on exactly that commit (deploy/ci-gate.mjs). The host receives
# `git archive` of that commit plus its file manifest, and builds, validates and switches it in a
# detached systemd unit, so a dropped connection or Ctrl+C cannot interrupt a deploy.
#
# Rehearsals (deploy/rehearsal/) set DEPLOY_REHEARSAL=1 with a local repository instead of
# GitHub and no CI gate; that mode refuses the production host.
set -euo pipefail

CANONICAL=https://github.com/sunny436/AI-Tutor-Webapp-backend.git
PRODUCTION=10.1.30.37
HOST=${DEPLOY_HOST:-root@$PRODUCTION}
REF="" OLDER=0 YES=0 PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=${2:?--ref needs a commit}; shift 2 ;;
    --older) OLDER=1; shift ;;
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    --yes) YES=1; shift ;;
    --with-migrations | --allow-older-schema | --prepare-only) PASS+=("$1"); shift ;;
    *) echo "unknown option: $1 (see the header of deploy/deploy.sh)" >&2; exit 2 ;;
  esac
done
stop() { echo "STOP: $*" >&2; exit 1; }

cd "$(git rev-parse --show-toplevel)"
if [ "${DEPLOY_REHEARSAL:-0}" = 1 ]; then
  SOURCE=${DEPLOY_REHEARSAL_SOURCE:?DEPLOY_REHEARSAL needs DEPLOY_REHEARSAL_SOURCE (a local repository)}
  case "$HOST" in *"$PRODUCTION"*) stop "rehearsal mode never deploys to production ($HOST)" ;; esac
  ssh "$HOST" 'test -f /etc/aichat/REHEARSAL' || stop "$HOST is not a rehearsal host (no /etc/aichat/REHEARSAL)"
else
  SOURCE=$CANONICAL
fi

echo "==> fetching main from $SOURCE"
git fetch --quiet "$SOURCE" "+refs/heads/main:refs/deploy/main"
MAIN=$(git rev-parse refs/deploy/main)
SHA=$(git rev-parse --verify "${REF:-$MAIN}^{commit}")
# Only commits OF main are releases: the tip, or an earlier point of main's own history. Commits
# that were merged into main from branches (or imported histories) are not complete releases.
git rev-list --first-parent "$MAIN" | grep -x "$SHA" >/dev/null || stop "$SHA is not a commit of main (only main's own commits are released)"
if [ "$SHA" != "$MAIN" ]; then
  [ "$OLDER" = 1 ] || stop "$SHA is older than main ($MAIN). To go back, use 'bun run rollback'; to redeploy an older commit on purpose, add --older."
fi
SUBJECT=$(git log -1 --format='%s' "$SHA")

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
if [ "${DEPLOY_REHEARSAL:-0}" = 1 ]; then
  printf '{"sha": "%s", "rehearsal": true, "operator": "%s"}\n' "$SHA" "$(git config user.name || echo unknown)" > "$WORK/ci.json"
  CI_SUMMARY="rehearsal: no CI gate"
else
  echo "==> checking CI for $SHA"
  bun deploy/ci-gate.mjs "$SHA" > "$WORK/ci.raw" || stop "CI has not passed for $SHA; nothing was deployed"
  # The CI evidence travels with the release (release.sh and status.sh show it); add who deployed.
  bun -e 'const fs=require("fs");const d=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));d.operator=process.argv[2];fs.writeFileSync(process.argv[3],JSON.stringify(d))' \
    "$WORK/ci.raw" "$(git config user.name || echo unknown)" "$WORK/ci.json"
  CI_SUMMARY="passed ($(bun -e 'console.log(JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).jobs.map(j=>j.name.split(" (")[0]).join(", "))' "$WORK/ci.raw"))"
fi
LIVE=$(ssh "$HOST" 'r=$(readlink -e /opt/aichat/current 2>/dev/null) && case "$r" in /opt/aichat/releases/*) basename "$r" ;; esac' || true)

cat <<EOF

  Deploy to $HOST
    release   $SHA
              $SUBJECT
    CI        $CI_SUMMARY
    live now  ${LIVE:-none (first release on this host)}
    options   ${PASS[*]:-none}
  Frontend and backend of this ONE commit go live together.
EOF
if [ -n "$LIVE" ] && [ "$LIVE" != "$SHA" ] && git merge-base --is-ancestor "$SHA" "$LIVE" 2>/dev/null; then
  echo "  WARNING: this is OLDER than what is live (a downgrade)."
fi
if [ "$YES" != 1 ]; then
  read -r -p "  Type the first 7 characters of the release to deploy it: " answer
  [ "$answer" = "${SHA:0:7}" ] || stop "not confirmed; nothing was deployed"
fi

ID=$(date -u +%Y%m%dT%H%M%S)-$RANDOM
UP="/opt/aichat/incoming/$SHA.$ID"
git archive --format=tar.gz --prefix="$SHA/" "$SHA" > "$WORK/$SHA.$ID.tar.gz"
sha256sum "$WORK/$SHA.$ID.tar.gz" | cut -d' ' -f1 > "$WORK/$SHA.$ID.sha256"
git ls-tree -r -z --full-tree "$SHA" > "$WORK/$SHA.$ID.manifest"
git show "$SHA:deploy/server/bootstrap.sh" > "$WORK/$SHA.$ID.bootstrap.sh"
git show "$SHA:deploy/server/verify-release.py" > "$WORK/$SHA.$ID.verify.py"
mv "$WORK/ci.json" "$WORK/$SHA.$ID.ci.json"
echo "==> uploading release $SHA ($(du -h "$WORK/$SHA.$ID.tar.gz" | cut -f1))"
tar -C "$WORK" -cf - "$SHA.$ID.tar.gz" "$SHA.$ID.sha256" "$SHA.$ID.manifest" "$SHA.$ID.bootstrap.sh" "$SHA.$ID.verify.py" "$SHA.$ID.ci.json" \
  | ssh "$HOST" 'mkdir -p /opt/aichat/incoming && tar -xf - -C /opt/aichat/incoming'

UNIT="aichat-deploy-${SHA:0:12}-${ID//[^0-9A-Za-z]/}"
echo "==> deploying in systemd unit $UNIT on $HOST (safe to lose this connection: it keeps going)"
# shellcheck disable=SC2029  # expanded here on purpose
ssh "$HOST" "journalctl -f -n0 -o cat -u $UNIT & J=\$!; systemd-run --unit=$UNIT --quiet --wait --collect -p Environment=HOME=/root bash $UP.bootstrap.sh $SHA $UP ${PASS[*]:-}; rc=\$?; sleep 2; kill \$J 2>/dev/null; exit \$rc"
