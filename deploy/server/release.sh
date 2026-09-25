#!/usr/bin/env bash
#
# Deploy ONE release (frontend + backend from the same commit) on the production host.
# Only ever started by deploy/server/bootstrap.sh, which deploy/deploy.sh runs as a detached
# systemd unit after checking that the commit is on GitHub's main and that CI passed on it.
#
#   --with-migrations     run pending database migrations (backup first, before the switch)
#   --allow-older-schema  deploy code that is older than the database schema
#   --prepare-only        build and validate, but do not switch production
#
# 1. prepare   build the release in its own directory from its locked dependencies; nothing
#              that serves users is touched
# 2. migrate   compare the release's migrations with the database; pending ones run only with
#              --with-migrations, after a fresh backup, while the current release keeps serving,
#              so they must be backward compatible (docs/deployment.md)
# 3. validate  start the release as trial copies on 127.0.0.1:4101 (API) and :3001 (web)
#              against the production database; both must report this release and prove
#              web -> API -> database
# 4. switch    stop web, point /opt/aichat/current at the release, restart the API, start web,
#              then prove the invariant; on failure switch back to the previous release
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

[ "${AICHAT_VIA_DEPLOY:-}" = 1 ] || die "releases are deployed with 'bun run deploy' only; never run release.sh by hand"
[ "$(id -u)" -eq 0 ] || die "run as root"
is_commit "$REL" || die "not a commit: $REL"
if [ "${AICHAT_LOCKED:-}" != 1 ]; then
  exec 9>/run/aichat-deploy.lock
  flock -n 9 || die "another deploy or rollback is running"
fi

cleanup_candidates() {
  systemctl stop aichat-candidate-api aichat-candidate-web >/dev/null 2>&1 || true
  systemctl reset-failed aichat-candidate-api aichat-candidate-web >/dev/null 2>&1 || true
  rm -f "$CAND_ENV"
}
trap cleanup_candidates EXIT

log "release $REL"
[ -d "$DIR/backend" ] && [ -d "$DIR/frontend" ] || die "$DIR is not an extracted release"
[ -f "$DIR/MANIFEST" ] && [ -f "$DIR/CI.json" ] || die "$DIR has no MANIFEST/CI.json: deploy with 'bun run deploy'"
for f in api.env web.env postgres.env; do [ -s "$SECRETS/$f" ] || die "missing $SECRETS/$f"; done
# Without it the frontend falls back to its development default (:4000), which on this host
# is not this API.
grep -qE '^API_BASE_URL=http://127\.0\.0\.1:4100/?$' "$SECRETS/web.env" \
  || die "$SECRETS/web.env must set API_BASE_URL=http://127.0.0.1:4100"
grep -qE '^NEXT_PUBLIC_SITE_URL=https?://.+' "$SECRETS/web.env" || die "$SECRETS/web.env must set NEXT_PUBLIC_SITE_URL"
command -v python3.12 >/dev/null || die "python3.12 is not installed (run deploy/install.sh)"
[ -x "$BUN" ] || die "bun is not installed at $BUN (run deploy/install.sh)"
[ "$("$BUN" --version)" = "$(tr -d '[:space:]' < "$DIR/.bun-version")" ]   || die "bun $("$BUN" --version) is installed; this release is built with $(cat "$DIR/.bun-version") (run deploy/install.sh)"
systemctl is-active --quiet aichat-postgres || die "aichat-postgres is not running"
PREVIOUS=$(current_release)
note "live now: ${PREVIOUS:-none (first release)}"
note "CI: $(python3.12 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("rehearsal (no CI)" if d.get("rehearsal") else ", ".join(j["name"].split(" (")[0] + " " + j["conclusion"] for j in d["jobs"]))' "$DIR/CI.json")"
OPERATOR=$(python3.12 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("operator", "unknown"))' "$DIR/CI.json")
[ -f "$DIR/RELEASE" ] || printf 'commit=%s\nprepared=%s\n' "$REL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DIR/RELEASE"
verify_release "$REL" || die "release $REL does not match its commit"

# ---------------------------------------------------------------- 1. prepare
log "1/4 prepare (in $DIR; production untouched)"
if [ ! -f "$DIR/backend/.venv/.ready" ] || [ ! -f "$DIR/frontend/.ready" ]; then preflight_resources; fi
if [ ! -f "$DIR/backend/.venv/.ready" ]; then
  build_step python3.12 -m venv "$DIR/backend/.venv"
  build_step "$DIR/backend/.venv/bin/python" -m pip install -q --require-hashes -r "$DIR/backend/requirements.lock"
  "$DIR/backend/.venv/bin/python" -m pip check >/dev/null || die "backend dependencies are inconsistent"
  touch "$DIR/backend/.venv/.ready"
fi
note "backend: locked dependencies installed (requirements.lock, hashes verified)"
# The frontend is built and served on the release's pinned Node (.node-version), as in CI.
ensure_node "$DIR"
NODE_BIN=$(node_bin_of "$DIR")
# NEXT_PUBLIC_* values are baked in at build time; changing them (or Node) requires a rebuild.
BUILD_ENV=$( { grep -E '^NEXT_PUBLIC_' "$SECRETS/web.env"; cat "$DIR/.node-version"; } | sha256sum | cut -d' ' -f1)
if [ "$(cat "$DIR/frontend/.ready" 2>/dev/null)" != "$BUILD_ENV" ]; then
  export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
  (cd "$DIR/frontend" && PATH="$NODE_BIN:$PATH" build_step "$BUN" install --frozen-lockfile)
  (cd "$DIR/frontend/apps/app" && set -a && . "$SECRETS/web.env" && set +a     && PATH="$NODE_BIN:$PATH" build_step "$BUN" run build)
  printf '%s' "$BUILD_ENV" > "$DIR/frontend/.ready"
fi
note "frontend: built with Node $("$NODE_BIN/node" --version) and bun $("$BUN" --version)"

# ---------------------------------------------------------------- 2. migrate
log "2/4 database migrations"
status=$(migration_status "$REL")
database=$(json_field database <<<"$status")
head=$(json_field head <<<"$status")
pending=$(json_field pending <<<"$status")
known=$(json_field database_known <<<"$status")
note "database: $database | this release: $head"
if [ "$known" != True ]; then
  [ "$ALLOW_OLDER" = 1 ] || die "the database ($database) was migrated by a NEWER release than $REL. Deploying older code
      onto it is only safe if those migrations were backward compatible; re-run with --allow-older-schema."
  note "older code on a newer schema: allowed by --allow-older-schema"
elif [ "$pending" != "[]" ]; then
  [ "$WITH_MIGRATIONS" = 1 ] || die "pending migrations $pending. They run BEFORE the switch while the current
      release keeps serving, so they must be backward compatible. Re-run with --with-migrations."
  [ "$PREPARE_ONLY" = 0 ] || die "--prepare-only never migrates; pending migrations: $pending"
  systemctl start aichat-pg-backup.service || die "the backup before migrating failed; nothing was migrated"
  backup=$(ls -1t /var/backups/aichat/aichat-*.dump 2>/dev/null | sed -n 1p)
  note "backup before migrating: $backup"
  systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
    -p WorkingDirectory="$DIR/backend" "$DIR/backend/.venv/bin/python" -m alembic upgrade head \
    || die "the migration failed (backup: $backup); nothing was switched"
  record "migrated $database -> $head for $REL (backup: $backup) by $OPERATOR"
  note "migrated: $pending"
  if [ -n "$PREVIOUS" ]; then
    check_chain "$WEB_PORT" aichat-api || note "WARNING: the live release fails its check after migrating"
  fi
else
  note "none pending"
fi

# ---------------------------------------------------------------- 3. validate
log "3/4 validate trial copies (API :$CAND_API, web :$CAND_WEB) against the production database"
cleanup_candidates
systemd-run --unit=aichat-candidate-api --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
  -p WorkingDirectory="$DIR/backend" "$DIR/backend/.venv/bin/python" -m uvicorn app.main:create_app \
  --factory --host 127.0.0.1 --port "$CAND_API"
wait_http "http://127.0.0.1:$CAND_API/ready" 90 || die "trial API not ready (journalctl -u aichat-candidate-api)"
note "trial API ready (database reachable, production settings accepted)"
(umask 077 && sed "s#^API_BASE_URL=.*#API_BASE_URL=http://127.0.0.1:$CAND_API#" "$SECRETS/web.env" > "$CAND_ENV")
systemd-run --unit=aichat-candidate-web --collect --quiet -p EnvironmentFile="$CAND_ENV" \
  -p Environment="PATH=$NODE_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  -p WorkingDirectory="$DIR/frontend/apps/app" "$BUN" x next start -p "$CAND_WEB" -H 127.0.0.1
wait_http "http://127.0.0.1:$CAND_WEB/login" 120 || die "trial web app not answering (journalctl -u aichat-candidate-web)"
note "trial web app serves /login"
[ "$(reported_release "http://127.0.0.1:$CAND_API/health")" = "$REL" ] || die "the trial API does not report release $REL"
[ "$(reported_release "http://127.0.0.1:$CAND_WEB/api/health")" = "$REL" ] || die "the trial web app does not report release $REL"
note "both trial copies report release $REL"
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
  record "validated $REL (not switched; live: ${PREVIOUS:-none}) by $OPERATOR"
  log "validated; production unchanged (--prepare-only)"
  exit 0
fi

# ---------------------------------------------------------------- 4. switch
log "4/4 switch production to $REL"
verify_release "$REL" || die "release $REL changed during the deploy; production unchanged"
STAMP=".before-$(date -u +%Y%m%d%H%M%S)"   # units replaced now are kept as <unit>$STAMP
export STAMP
if activate "$REL"; then
  push_live "$REL"
  record "deployed $REL (previous: ${PREVIOUS:-none}) by $OPERATOR"
  systemctl enable --quiet aichat-api.service aichat-web.service || note "(could not enable the units at boot)"
else
  note "live checks FAILED on $REL"
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$REL" ]; then
    log "rolling back to $PREVIOUS"
    if activate "$PREVIOUS"; then
      record "FAILED $REL, rolled back to $PREVIOUS by $OPERATOR"
      die "release $REL failed its live checks; production is back on $PREVIOUS"
    fi
    record "FAILED $REL, rollback to $PREVIOUS ALSO failed"
    die "rollback to $PREVIOUS failed too: investigate now (journalctl -u aichat-api -u aichat-web)"
  fi
  # First release on a host that ran the old two-checkout layout: put back the unit files
  # activate() replaced a moment ago, and restart the old layout.
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
    if wait_http "http://127.0.0.1:$API_PORT/ready" 90 && wait_http "http://127.0.0.1:$WEB_PORT/login" 120; then
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
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$public/login" || true)
if [ "$code" = 200 ]; then note "public $public/login -> 200"; else note "WARNING: public $public/login -> $code (tunnel/DNS?)"; fi

# Keep the live release and the two before it on the live stack (two rollbacks deep); delete
# older builds. Never the live one.
keep=$( { live_stack | tail -3; printf '%s\n' "$REL" "$PREVIOUS"; } | sort -u | tr '\n' ' ')
while read -r old; do
  case " $keep " in *" $old "*) continue ;; esac
  rm -rf "${RELEASES:?}/$old"
  note "pruned old release $old"
done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended -regex '.*/[0-9a-f]{40}' -printf '%f\n')
find "$ROOT/incoming" -maxdepth 1 -type f -mtime +2 -delete 2>/dev/null || true
log "live: $REL (previous: ${PREVIOUS:-none}). Status: bun run status. Roll back: bun run rollback"
