#!/usr/bin/env bash
#
# THE production deployment command. AI Tutor is released as one application: one commit ->
# one release (frontend + backend together) -> production. There is no other way.
#
#   bun run deploy -- --ref <commit>                      the commit checked out here (normal case)
#   bun run deploy -- --ref <commit> --with-migrations    the release has pending database migrations
#   bun run deploy -- --ref <commit> --prepare-only       build + validate on the host, do not switch
#   bun run deploy -- --ref <commit> --older              an OLDER commit of main (prefer `bun run rollback`)
#
#   --allow-older-schema   deploy code older than the database schema (backward-compatible only)
#   --yes                  skip the typed confirmation (automation)
#   --host <user@host>     default: root@10.1.30.37 (or $DEPLOY_HOST)
#
# The operator's order (docs/deployment.md, "Releasing"): commit -> push the branch to GitHub ->
# `bun run verify` -> `bun run deploy -- --ref <commit>` -> `bun run status` -> merge into main.
#
# Checked here, all before anything reaches the host, failing closed:
#   1. --ref is the commit checked out here (HEAD); the working tree is clean; git fsck is clean
#   2. `bun run verify` passed on exactly this commit and tree (deploy/local-gate.mjs)
#   3. GitHub (the pinned repository URL, fetched now) holds the commit on a branch, and the commit
#      contains GitHub's main (with --older: it is a commit of main's own history)
#   4. the commit contains the live release, which is itself on GitHub, so a deploy can never
#      silently drop commits that are live (with --older: it is an ancestor of the live release)
# GitHub Actions is not consulted: CI still runs on every push and pull request, and
# `bun run status` reports its verdict on the live release. The host receives `git archive` of
# the commit, its file manifest, the verification evidence and log, and the live release this
# pre-flight saw: under its deploy lock it refuses if production changed since (another deploy or
# a rollback). It builds, validates and switches in a detached systemd unit, so a dropped
# connection or Ctrl+C cannot interrupt a deploy.
#
# Rehearsals (deploy/rehearsal/) set DEPLOY_REHEARSAL=1 with a local repository standing in for
# GitHub; that mode accepts rehearsal-marked evidence and refuses the production host.
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
else
  SOURCE=$CANONICAL
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------- 1. the exact commit checked out here
[ -n "$REF" ] || stop "--ref <commit> is required: the exact commit to release, checked out here (docs/deployment.md, \"Releasing\")"
SHA=$(git rev-parse --verify --quiet "$REF^{commit}") || stop "$REF is not a commit in this repository"
HEAD_SHA=$(git rev-parse HEAD)
[ "$SHA" = "$HEAD_SHA" ] || stop "--ref $REF is $SHA, but this checkout is at $HEAD_SHA: check out the release, verify it, then deploy it"
[ -z "$(git status --porcelain --untracked-files=normal)" ] || stop "the working tree has uncommitted or untracked changes: only committed, verified code is released"
git fsck --strict --no-dangling > "$WORK/fsck" 2>&1 || stop "git fsck found a problem in this repository: $(head -3 "$WORK/fsck" | tr '\n' ' ')"
SUBJECT=$(git log -1 --format='%s' "$SHA")

# ---------------------------------------------------------------- 2. verified on this machine
echo "==> local verification of $SHA"
bun deploy/local-gate.mjs "$SHA" > "$WORK/evidence.json" || stop "$SHA has no passing verification: run 'bun run verify' with it checked out (nothing was deployed)"
# (Bun reads the JSON from stdin: on Windows it cannot open Git Bash's /tmp paths.)
VERIFIED=$(bun -e 'const d=JSON.parse(require("fs").readFileSync(0,"utf8")); console.log(d.rehearsal ? "rehearsal evidence" : `${d.machine} at ${d.finished_at} (${d.runner?.os ?? "?"}): ${d.jobs.map(j=>j.name.split(" (")[0]).join(", ")} passed`)' < "$WORK/evidence.json")
[ -n "$VERIFIED" ] || stop "could not read the verification evidence"

# ---------------------------------------------------------------- 3. on GitHub, containing GitHub's main
echo "==> fetching the branches of $SOURCE"
git fetch --quiet --prune "$SOURCE" "+refs/heads/*:refs/deploy/heads/*" 2> "$WORK/fetch" \
  || stop "cannot fetch $SOURCE ($(head -1 "$WORK/fetch")): GitHub must hold a release before production does. Try again when it is reachable; 'bun run rollback' works without it."
MAIN=$(git rev-parse --verify --quiet refs/deploy/heads/main) || stop "$SOURCE has no main branch"
BRANCHES=$(git for-each-ref --contains "$SHA" --format='%(refname)' refs/deploy/heads | sed 's#^refs/deploy/heads/##' | paste -sd' ' -)
[ -n "$BRANCHES" ] || stop "$SHA is on no branch of $SOURCE: push it first (git push tutor <branch>), so every release is on GitHub before it is in production"
if git merge-base --is-ancestor "$MAIN" "$SHA"; then
  AHEAD=$(git rev-list --count "$MAIN..$SHA")
  if [ "$AHEAD" = 0 ]; then TO_MAIN="is GitHub's main"; else TO_MAIN="is $AHEAD commit(s) ahead of GitHub's main: merge it into main after deploying"; fi
elif [ "$OLDER" = 1 ] && git rev-list --first-parent "$MAIN" | grep -qx "$SHA"; then
  TO_MAIN="is an OLDER commit of GitHub's main (--older)"
else
  stop "$SHA does not contain GitHub's main (${MAIN:0:12}): merge main into it first (to redeploy an older commit of main on purpose, add --older)"
fi

# ---------------------------------------------------------------- 4. the live release
if [ "${DEPLOY_REHEARSAL:-0}" = 1 ]; then
  ssh "$HOST" 'test -f /etc/aichat/REHEARSAL' || stop "$HOST is not a rehearsal host (no /etc/aichat/REHEARSAL)"
fi
REPLY_LIVE=$(ssh "$HOST" 'r=$(readlink -e /opt/aichat/current 2>/dev/null); case "$r" in /opt/aichat/releases/*) echo "live=$(basename "$r")" ;; *) echo "live=" ;; esac') \
  || stop "cannot read the live release from $HOST"
case "$REPLY_LIVE" in live=*) LIVE=${REPLY_LIVE#live=} ;; *) stop "unexpected answer from $HOST: $REPLY_LIVE" ;; esac
if [ -n "$LIVE" ]; then
  [[ "$LIVE" =~ ^[0-9a-f]{40}$ ]] || stop "the live release on $HOST is not a commit: $LIVE"
  if ! git cat-file -e "$LIVE^{commit}" 2>/dev/null || [ -z "$(git for-each-ref --contains "$LIVE" refs/deploy/heads | head -1)" ]; then
    stop "the live release $LIVE is on no branch of $SOURCE: find out where it came from before replacing it"
  fi
  if git merge-base --is-ancestor "$LIVE" "$SHA"; then
    if [ "$LIVE" = "$SHA" ]; then TO_LIVE="is the live release (a redeploy)"; else TO_LIVE="contains it, plus $(git rev-list --count "$LIVE..$SHA") commit(s)"; fi
  elif [ "$OLDER" = 1 ] && git merge-base --is-ancestor "$SHA" "$LIVE"; then
    TO_LIVE="is OLDER than it: a downgrade"
  else
    stop "$SHA does not contain the live release ${LIVE:0:12}: it would remove commits that are live. Merge the live release into it first (or go back with 'bun run rollback')"
  fi
else
  TO_LIVE="is the first release on this host"
fi

cat <<EOF

  Deploy to $HOST
    release   $SHA
              $SUBJECT
    verified  $VERIFIED
    GitHub    on: $BRANCHES
              this release $TO_MAIN
    live now  ${LIVE:-none}
              this release $TO_LIVE
    options   ${PASS[*]:-none}
  Frontend and backend of this ONE commit go live together.
EOF
if [ "$YES" != 1 ]; then
  read -r -p "  Type the first 7 characters of the release to deploy it: " answer
  [ "$answer" = "${SHA:0:7}" ] || stop "not confirmed; nothing was deployed"
fi

# The evidence travels with the release (release.sh, status.sh and the host's HISTORY show it),
# with who deployed it, from where, and what GitHub held at that moment.
bun -e 'const [operator,machine,main,branches,live]=process.argv.slice(1);
  const d=JSON.parse(require("fs").readFileSync(0,"utf8"));
  d.deploy={operator,machine,github_main:main,github_branches:branches.split(" "),expected_live:live||null};
  d.operator=operator; console.log(JSON.stringify(d));' \
  "$(git config user.name || echo unknown)" "$(hostname)" "$MAIN" "$BRANCHES" "$LIVE" < "$WORK/evidence.json" > "$WORK/ci.json"
[ -s "$WORK/ci.json" ] || stop "could not prepare the release evidence"

ID=$(date -u +%Y%m%dT%H%M%S)-$RANDOM
UP="/opt/aichat/incoming/$SHA.$ID"
git archive --format=tar.gz --prefix="$SHA/" "$SHA" > "$WORK/$SHA.$ID.tar.gz"
sha256sum "$WORK/$SHA.$ID.tar.gz" | cut -d' ' -f1 > "$WORK/$SHA.$ID.sha256"
git ls-tree -r -z --full-tree "$SHA" > "$WORK/$SHA.$ID.manifest"
git show "$SHA:deploy/server/bootstrap.sh" > "$WORK/$SHA.$ID.bootstrap.sh"
git show "$SHA:deploy/server/verify-release.py" > "$WORK/$SHA.$ID.verify.py"
mv "$WORK/ci.json" "$WORK/$SHA.$ID.ci.json"
if [ -f ".deploy/verified/$SHA.log" ]; then gzip -c ".deploy/verified/$SHA.log" > "$WORK/$SHA.$ID.verify.log.gz"; else : | gzip -c > "$WORK/$SHA.$ID.verify.log.gz"; fi
# Nothing moved while this ran: what is uploaded is still what was checked.
[ "$(git rev-parse HEAD)" = "$SHA" ] || stop "HEAD moved during the deploy; nothing was deployed"
echo "==> uploading release $SHA ($(du -h "$WORK/$SHA.$ID.tar.gz" | cut -f1))"
tar -C "$WORK" -cf - "$SHA.$ID.tar.gz" "$SHA.$ID.sha256" "$SHA.$ID.manifest" "$SHA.$ID.bootstrap.sh" "$SHA.$ID.verify.py" "$SHA.$ID.ci.json" "$SHA.$ID.verify.log.gz" \
  | ssh "$HOST" 'mkdir -p /opt/aichat/incoming && tar -xf - -C /opt/aichat/incoming'

UNIT="aichat-deploy-${SHA:0:12}-${ID//[^0-9A-Za-z]/}"
echo "==> deploying in systemd unit $UNIT on $HOST (safe to lose this connection: it keeps going)"
# The expected live release is checked again on the host, under the deploy lock. The client
# address ($SSH_CONNECTION, expanded on the host) is recorded in the host's HISTORY.
# shellcheck disable=SC2029  # expanded here on purpose
ssh "$HOST" "journalctl -f -n0 -o cat -u $UNIT & J=\$!; systemd-run --unit=$UNIT --quiet --wait --collect -p Environment=HOME=/root -p Environment=AICHAT_EXPECT_LIVE=${LIVE:-none} -p \"Environment=AICHAT_SSH_CLIENT=\${SSH_CONNECTION// /,}\" bash $UP.bootstrap.sh $SHA $UP ${PASS[*]:-}; rc=\$?; sleep 2; kill \$J 2>/dev/null; exit \$rc"
