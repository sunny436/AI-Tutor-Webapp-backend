#!/usr/bin/env bash
#
# THE deployment command: one commit -> one release (frontend + backend) -> production.
# Run from a workstation that can read the GitHub repository and ssh to the host
# (Git Bash on Windows works). From the repository root:
#
#   bun run deploy                                  # the tip of main on GitHub
#   bun run deploy -- --ref <commit> --with-migrations
#   bash deploy/deploy.sh --prepare-only            # build + validate on the host, do not switch
#
#   --ref <commit|tag|branch>   what to deploy (default: <remote>/main)
#   --host <user@host>          default: $DEPLOY_HOST or root@10.1.30.37
#   --with-migrations           allow pending migrations to run (before the switch)
#   --allow-older-schema        allow code older than the database schema
#   --prepare-only              build and validate only; production keeps its release
#   --allow-unpushed            deploy a commit that is not on GitHub's main (emergencies only)
#
# The host needs no GitHub access. This script sends `git archive` of exactly one commit;
# the host builds it into /opt/aichat/releases/<commit>/, validates it, and only then switches
# /opt/aichat/current. See docs/deployment.md.
set -euo pipefail

HOST=${DEPLOY_HOST:-root@10.1.30.37}
REF="" PASS=() ALLOW_UNPUSHED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=${2:?--ref needs a value}; shift 2 ;;
    --host) HOST=${2:?--host needs a value}; shift 2 ;;
    --with-migrations | --allow-older-schema | --prepare-only) PASS+=("$1"); shift ;;
    --allow-unpushed) ALLOW_UNPUSHED=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"
# The canonical remote: $DEPLOY_REMOTE, else the one pointing at the GitHub repository.
REMOTE=${DEPLOY_REMOTE:-$(git remote -v | awk '/AI-Tutor-Webapp(-backend)?(\.git)? \(fetch\)/ {print $1; exit}')}
REMOTE=${REMOTE:-origin}
echo "==> fetching $REMOTE"
git fetch --quiet "$REMOTE"
REF=${REF:-$REMOTE/main}
SHA=$(git rev-parse --verify "$REF^{commit}")
if [ "$ALLOW_UNPUSHED" = 0 ] && ! git merge-base --is-ancestor "$SHA" "$REMOTE/main"; then
  echo "STOP: $SHA is not on $REMOTE/main. Production only runs commits that are on main." >&2
  echo "      (--allow-unpushed overrides this for emergencies.)" >&2
  exit 1
fi
echo "==> release $SHA"
git log -1 --format='    %s (%an, %ad)' --date=short "$SHA"

ARCHIVE=$(mktemp)
trap 'rm -f "$ARCHIVE"' EXIT
git archive --format=tar.gz --prefix="$SHA/" "$SHA" > "$ARCHIVE"
SUM=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
echo "==> uploading $(du -h "$ARCHIVE" | cut -f1) to $HOST"
ssh "$HOST" "mkdir -p /opt/aichat/incoming /opt/aichat/releases && cat > /opt/aichat/incoming/$SHA.tar.gz" < "$ARCHIVE"

# Extract into a temporary directory and rename, so a release directory is always complete;
# then run the release's OWN server script (never an older copy).
ssh "$HOST" bash -s -- "$SHA" "$SUM" "${PASS[@]}" <<'REMOTE'
set -euo pipefail
SHA=$1 SUM=$2; shift 2
cd /opt/aichat
[ "$(sha256sum "incoming/$SHA.tar.gz" | cut -d' ' -f1)" = "$SUM" ] || { echo "STOP: upload corrupted" >&2; exit 1; }
if [ ! -d "releases/$SHA" ]; then
  rm -rf "releases/.extract-$SHA" && mkdir "releases/.extract-$SHA"
  tar -xzf "incoming/$SHA.tar.gz" -C "releases/.extract-$SHA"
  mv "releases/.extract-$SHA/$SHA" "releases/$SHA" && rmdir "releases/.extract-$SHA"
fi
exec bash "releases/$SHA/deploy/server/release.sh" "$SHA" "$@"
REMOTE
