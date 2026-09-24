#!/usr/bin/env bash
#
# Deploy ONE release (frontend + backend from the same commit) on the production host.
# Started by deploy/deploy.sh, always from the release being deployed:
#
#   bash /opt/aichat/releases/<commit>/deploy/server/release.sh <commit> [options]
#
#   --with-migrations     run pending database migrations (before the switch)
#   --allow-older-schema  deploy code that is older than the database schema
#   --prepare-only        build and validate, but do not switch production
#
# 1. prepare   build the release in its own directory: backend venv, frontend install + build.
#              Nothing that serves users is touched.
# 2. migrate   compare the release's migrations with the database. Pending migrations run only
#              with --with-migrations, BEFORE the switch, while the current release keeps
#              serving, so they must be backward compatible (docs/deployment.md).
# 3. validate  start the release as trial copies on 127.0.0.1:4101 (API) and :3001 (web) against
#              the production database, and prove web -> API -> database.
# 4. switch    point /opt/aichat/current at the release and restart the API, then the web app
#              (a few seconds). If the live checks fail, switch back to the previous release
#              automatically.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

REL=${1:?usage: release.sh <commit> [--with-migrations] [--allow-older-schema] [--prepare-only]}
shift
WITH_MIGRATIONS=0 ALLOW_OLDER=0 PREPARE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --with-migrations) WITH_MIGRATIONS=1 ;;
    --allow-older-schema) ALLOW_OLDER=1 ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    *) die "unknown option $arg" ;;
  esac
done
DIR="$RELEASES/$REL"
CAND_API=4101 CAND_WEB=3001
CAND_ENV=/run/aichat-candidate-web.env

[ "$(id -u)" -eq 0 ] || die "run as root"
exec 9>/run/aichat-deploy.lock
flock -n 9 || die "another deploy or rollback is running"

cleanup_candidates() {
  systemctl stop aichat-candidate-api aichat-candidate-web >/dev/null 2>&1 || true
  systemctl reset-failed aichat-candidate-api aichat-candidate-web >/dev/null 2>&1 || true
  rm -f "$CAND_ENV"
}
trap cleanup_candidates EXIT

log "release $REL"
[ -d "$DIR/backend" ] && [ -d "$DIR/frontend" ] || die "$DIR is not an extracted release"
for f in api.env web.env postgres.env; do [ -s "$SECRETS/$f" ] || die "missing $SECRETS/$f"; done
# Without it the frontend falls back to its development default (:4000), which on this host
# is not this API.
grep -qE '^API_BASE_URL=http://127\.0\.0\.1:4100/?$' "$SECRETS/web.env" \
  || die "$SECRETS/web.env must set API_BASE_URL=http://127.0.0.1:4100"
command -v python3.12 >/dev/null || die "python3.12 is not installed (run deploy/install.sh)"
[ -x "$BUN" ] || die "bun is not installed at $BUN (run deploy/install.sh)"
systemctl is-active --quiet aichat-postgres || die "aichat-postgres is not running"
PREVIOUS=$(current_release)
note "live now: ${PREVIOUS:-none (first release)}"
[ "$PREVIOUS" != "$REL" ] || note "this release is already live; it will be rebuilt if needed and re-validated"
[ -f "$DIR/RELEASE" ] || printf 'commit=%s\nprepared=%s\n' "$REL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DIR/RELEASE"

# ---------------------------------------------------------------- 1. prepare
log "1/4 prepare (in $DIR; production untouched)"
if [ ! -f "$DIR/backend/.venv/.ready" ]; then
  python3.12 -m venv "$DIR/backend/.venv"
  "$DIR/backend/.venv/bin/python" -m pip install -q --upgrade pip
  "$DIR/backend/.venv/bin/python" -m pip install -q -r "$DIR/backend/requirements.txt"
  touch "$DIR/backend/.venv/.ready"
fi
note "backend venv ready"
if [ ! -f "$DIR/frontend/.ready" ]; then
  PATH="$(dirname "$BUN"):$PATH"
  export PATH TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
  (cd "$DIR/frontend" && "$BUN" install --frozen-lockfile)
  # NEXT_PUBLIC_* values are baked in at build time: build with production's web.env.
  (cd "$DIR/frontend" && set -a && . "$SECRETS/web.env" && set +a && "$BUN" run build)
  touch "$DIR/frontend/.ready"
fi
note "frontend built"

# ---------------------------------------------------------------- 2. migrate
log "2/4 database migrations"
status=$(migration_status "$REL")
note "database: $(json_field database <<<"$status") | this release: $(json_field head <<<"$status")"
pending=$(json_field pending <<<"$status")
if [ "$(json_field database_known <<<"$status")" != True ]; then
  [ "$ALLOW_OLDER" = 1 ] || die "the database was migrated by a NEWER release than $REL. Deploying older code
      onto it is only safe if those migrations were backward compatible; re-run with --allow-older-schema."
  note "older code on a newer schema: allowed by --allow-older-schema"
elif [ "$pending" != "[]" ]; then
  [ "$WITH_MIGRATIONS" = 1 ] || die "pending migrations $pending. They run BEFORE the switch while the current
      release keeps serving, so they must be backward compatible. Re-run with --with-migrations."
  [ "$PREPARE_ONLY" = 0 ] || die "--prepare-only never migrates; pending migrations: $pending"
  systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
    -p WorkingDirectory="$DIR/backend" "$DIR/backend/.venv/bin/python" -m alembic upgrade head
  note "migrated: $pending"
else
  note "none pending"
fi

# ---------------------------------------------------------------- 3. validate
log "3/4 validate trial copies (API :$CAND_API, web :$CAND_WEB) against the production database"
cleanup_candidates
systemd-run --unit=aichat-candidate-api --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
  -p WorkingDirectory="$DIR/backend" "$DIR/backend/.venv/bin/python" -m uvicorn app.main:create_app \
  --factory --host 127.0.0.1 --port "$CAND_API"
wait_http "http://127.0.0.1:$CAND_API/ready" 60 || die "trial API not ready (journalctl -u aichat-candidate-api)"
note "trial API ready (database reachable, production settings accepted)"
(umask 077 && sed "s#^API_BASE_URL=.*#API_BASE_URL=http://127.0.0.1:$CAND_API#" "$SECRETS/web.env" > "$CAND_ENV")
systemd-run --unit=aichat-candidate-web --collect --quiet -p EnvironmentFile="$CAND_ENV" \
  -p WorkingDirectory="$DIR/frontend/apps/app" "$BUN" x next start -p "$CAND_WEB" -H 127.0.0.1
wait_http "http://127.0.0.1:$CAND_WEB/login" 90 || die "trial web app not answering (journalctl -u aichat-candidate-web)"
note "trial web app serves /login"
check_chain "$CAND_WEB" aichat-candidate-api || die "trial web app could not reach the trial API"
if systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" -p WorkingDirectory="$DIR/backend" \
  "$DIR/backend/.venv/bin/python" -c '
import asyncio
from app.llm.base import ChatMessage, GenerationOptions
from app.llm.factory import build_llm
from app.settings import Settings
async def main():
    stream = await build_llm(Settings()).stream([ChatMessage(role="user", content="Reply with OK")], GenerationOptions(max_output_tokens=5))
    async for _ in stream.parts:
        return
asyncio.run(main())' >/dev/null 2>&1; then
  note "LLM answers"
else
  note "WARNING: the LLM did not answer. Chat replies will fail until it does (not a release problem)."
fi
cleanup_candidates

if [ "$PREPARE_ONLY" = 1 ]; then
  record "validated $REL (not switched; live: ${PREVIOUS:-none})"
  log "validated; production unchanged (--prepare-only)"
  exit 0
fi

# ---------------------------------------------------------------- 4. switch
log "4/4 switch production to $REL"
STAMP=".before-$(date -u +%Y%m%d%H%M%S)"
BACKUP_SUFFIX=$STAMP bash "$DIR/deploy/server/install-units.sh" "$DIR"
if activate "$REL"; then
  record "deployed $REL (previous: ${PREVIOUS:-none})"
  systemctl enable --quiet aichat-api.service aichat-web.service  # start at boot (first release on a host)
else
  note "live checks FAILED on $REL"
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$REL" ]; then
    log "rolling back to $PREVIOUS"
    if activate "$PREVIOUS"; then
      record "FAILED $REL, rolled back to $PREVIOUS"
      die "release $REL failed its live checks; production is back on $PREVIOUS"
    fi
    record "FAILED $REL, rollback to $PREVIOUS ALSO failed"
    die "rollback to $PREVIOUS failed too: investigate now (journalctl -u aichat-api -u aichat-web)"
  fi
  # First release on a host that ran the old two-checkout layout: put back the unit files
  # install-units.sh replaced a moment ago, and restart the old layout.
  restored=0
  for saved in /etc/systemd/system/aichat-*"$STAMP"; do
    [ -f "$saved" ] || continue
    mv -f "$saved" "${saved%"$STAMP"}"
    restored=1
  done
  if [ "$restored" = 1 ]; then
    log "restoring the previous (pre-release) units"
    rm -f "$CURRENT"
    systemctl daemon-reload
    systemctl restart aichat-api aichat-web
    if wait_http "http://127.0.0.1:$API_PORT/ready" 60 && wait_http "http://127.0.0.1:$WEB_PORT/login" 90; then
      record "FAILED $REL (first release), restored the previous units"
      die "release $REL failed its live checks; the previous setup is running again"
    fi
    record "FAILED $REL (first release), restoring the previous units ALSO failed"
    die "the previous setup did not come back either: investigate now (docs/rollback.md)"
  fi
  record "FAILED $REL (no previous release to roll back to)"
  die "release $REL failed its live checks and there is no previous release (see docs/rollback.md)"
fi
public=$(sed -n 's/^NEXT_PUBLIC_SITE_URL=//p' "$SECRETS/web.env")
if [ -n "$public" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$public/login" || true)
  note "public $public/login -> $code"
fi

# Keep the live release, the previous one and one more; delete older builds.
keep="$REL ${PREVIOUS:-}"
for old in $(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended   -regex '.*/[0-9a-f]{40}' -printf '%T@ %f
' | sort -rn | awk '{print $2}'); do
  case " $keep " in *" $old "*) continue ;; esac
  if [ "$(wc -w <<<"$keep")" -lt 3 ]; then keep="$keep $old"; continue; fi
  rm -rf "${RELEASES:?}/$old" "$ROOT/incoming/$old.tar.gz"
  note "pruned old release $old"
done
log "live: $REL (previous: ${PREVIOUS:-none}). Roll back with: bash deploy/rollback.sh"
