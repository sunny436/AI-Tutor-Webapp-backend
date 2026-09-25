#!/usr/bin/env bash
#
# First step of a deploy on the host. deploy/deploy.sh uploads this file (taken from the commit
# being deployed, never a working tree) and starts it as a detached systemd unit, so a dropped
# SSH connection or Ctrl+C on the workstation can never interrupt a deploy half-way:
#
#   systemd-run --unit=aichat-deploy-<commit>-<id> --wait bash <upload>.bootstrap.sh <commit> <upload> [options]
#
# It holds the deploy lock for the whole deploy, checks the upload, extracts the release
# atomically, proves the release's files are exactly the commit, then hands over to that
# release's own deploy/server/release.sh. Output goes to the journal and to
# /opt/aichat/releases/<commit>/deploy-<id>.log.
set -euo pipefail

SHA=${1:?usage: bootstrap.sh <commit> <upload> [options]}
UPLOAD=${2:?usage: bootstrap.sh <commit> <upload> [options]}
shift 2
ROOT=/opt/aichat
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "STOP: not a commit: $SHA" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "STOP: run as root" >&2; exit 1; }

exec 9>/run/aichat-deploy.lock
flock -n 9 || { echo "STOP: another deploy or rollback is running" >&2; exit 1; }

cd "$ROOT"
[ "$(sha256sum "$UPLOAD.tar.gz" | cut -d' ' -f1)" = "$(cat "$UPLOAD.sha256")" ] \
  || { echo "STOP: the upload is corrupted" >&2; exit 1; }
mkdir -p releases
if [ ! -d "releases/$SHA" ]; then
  rm -rf "releases/.extract-$SHA" && mkdir "releases/.extract-$SHA"
  tar -xzf "$UPLOAD.tar.gz" -C "releases/.extract-$SHA"
  mv "releases/.extract-$SHA/$SHA" "releases/$SHA" && rmdir "releases/.extract-$SHA"
fi
install -m 644 "$UPLOAD.manifest" "releases/$SHA/MANIFEST"
install -m 644 "$UPLOAD.ci.json" "releases/$SHA/CI.json"

LOG="$ROOT/releases/$SHA/deploy-${UPLOAD##*.}.log"
{
  echo "==> deploy $SHA (log: $LOG)"
  # The verifier also comes from the upload, so a modified release cannot vouch for itself.
  if ! python3.12 "$UPLOAD.verify.py" "releases/$SHA"; then
    echo "STOP: release $SHA does not match its commit" >&2
    exit 1
  fi
  AICHAT_VIA_DEPLOY=1 AICHAT_LOCKED=1 bash "releases/$SHA/deploy/server/release.sh" "$SHA" "$@"
} 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
