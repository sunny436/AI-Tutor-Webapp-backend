#!/usr/bin/env bash
#
# Move production to one commit, doing only what that commit needs. deploy/deploy.sh (and
# rollback.sh) run it on the host as a detached systemd unit, from a copy of the deploying
# checkout's deploy/ directory (so a rollback to an older commit still uses today's tooling):
#
#   bash <tools>/deploy/server/update.sh <commit>
#
# 1. Under the host's deploy lock, the production checkout /opt/aichat/app becomes <commit>
#    (git reset --hard: .venv, node_modules and the frontend builds are untracked and stay).
# 2. Content keys (lib.sh) say what changed, and only that runs, in this order:
#      backend deps   requirements.lock              pip install --require-hashes into the venv
#      frontend deps  package.json / bun.lock        bun install --frozen-lockfile
#      frontend       frontend/, .node-version, NEXT_PUBLIC_*   built BESIDE the served build
#      units          deploy/systemd                 changed unit files rewritten
#      migrations     backend/alembic/versions       backup, then upgrade, only if pending
#      backend        backend/ (or its unit)         restart aichat-api
#      frontend       (built above, or its unit)     swap the build in, restart aichat-web
#    A commit that changes none of them (docs, tests) rebuilds and restarts nothing.
# 3. Local smoke: both units active, API /health + /ready, web /login, web -> API -> database.
# Any failure: "STOP: ..." and a non-zero exit. A part's key advances only once it runs the new
# code, so the next deploy redoes whatever failed. The first run on a host still on the old
# release layout (/opt/aichat/current) is the cutover: if it fails, the old units come back.
set -euo pipefail
SHA=${1:?usage: update.sh <commit>}
TOOLS=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
. "$TOOLS/deploy/server/lib.sh"

CUTOVER=0 UNITS_CHANGED=0 STAMP=".before-$(date -u +%Y%m%d%H%M%S)" DONE=() K_BACK="" K_FRONT=""
START=$(date +%s)
took() { printf '%ss' "$(($(date +%s) - START))"; }
step() { log "[$(took)] $*"; }
status_line() { # what each part runs now: the last line deploy.sh and status.sh read
  [ -n "$K_BACK" ] || return 0
  printf '@@STATUS checkout=%s backend=%s frontend=%s backend_current=%s frontend_current=%s\n' "$SHA" \
    "$(running_commit backend)" "$(running_commit frontend)" \
    "$([ "$(running_key backend)" = "$K_BACK" ] && echo yes || echo no)" \
    "$([ "$(running_key frontend)" = "$K_FRONT" ] && echo yes || echo no)"
}
restore_old_units() { # the cutover failed after installing the new units: put the old ones back
  local saved restored=0
  for saved in /etc/systemd/system/aichat-*"$STAMP"; do
    [ -f "$saved" ] || continue
    mv -f "$saved" "${saved%"$STAMP"}"
    restored=1
  done
  [ "$restored" = 1 ] || return 0
  log "cutover failed: restoring the release-layout units ($(readlink -f "$ROOT/current"))"
  systemctl daemon-reload
  systemctl restart aichat-api aichat-web
  if wait_http "http://127.0.0.1:$API_PORT/ready" 90 && wait_http "http://127.0.0.1:$WEB_PORT/login" 120; then
    note "production is back on the release layout"
  else
    note "the previous units did not come back either: investigate now (docs/rollback.md)"
  fi
}
on_failure() {
  if [ "$CUTOVER" = 1 ] && [ "$UNITS_CHANGED" = 1 ]; then restore_old_units; fi
  printf '%s FAILED %s by %s (ssh %s) after: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" \
    "${AICHAT_OPERATOR:-unknown}" "${AICHAT_SSH_CLIENT:-local}" "${DONE[*]:-nothing}" >> "$HISTORY" 2>/dev/null || true
}
trap 'rc=$?; if [ "${MARKER_OWNED:-0}" = 1 ]; then rm -f /run/aichat-deploying; fi; if [ "$rc" != 0 ]; then on_failure; fi; status_line; printf "@@END %s\n" "$rc"' EXIT

is_commit "$SHA" || die "not a commit: $SHA"
[ "$(id -u)" -eq 0 ] || die "run as root"
exec 9>/run/aichat-deploy.lock
flock -n 9 || die "another deploy is running; nothing was changed"
# While the checkout and its venv change, the API's file worker makes no new claims
# (app/files/processing.py DEPLOY_MARKER); removed on exit, whatever happens.
touch /run/aichat-deploying && MARKER_OWNED=1

# ---------------------------------------------------------------- 1. the checkout
step "production checkout -> $SHA"
[ -d "$APP/.git" ] || git clone -q "$APP_GIT" "$APP"
git -C "$APP" fetch -q origin
git -C "$APP" cat-file -e "$SHA^{commit}" 2>/dev/null || die "$SHA is not in $APP_GIT"
mkdir -p "$STATE"
PREV=$(cat "$STATE/deployed" 2>/dev/null || true)
if [ -z "$PREV" ] && [ -L "$ROOT/current" ]; then CUTOVER=1 PREV=$(basename "$(readlink -f "$ROOT/current")"); fi
git -C "$APP" reset -q --hard "$SHA"
printf 'commit=%s\n' "$SHA" > "$APP/RELEASE"
note "$(git -C "$APP" log -1 --format='%h %s')"
[ "$CUTOVER" = 1 ] && note "first deploy on this host: moving from the release layout ($PREV) to $APP"

# ---------------------------------------------------------------- 2. what this commit needs
WEBDIR="$APP/frontend/apps/app"
K_BDEPS=$(key_backend_deps) K_FDEPS=$(key_frontend_deps) K_MIG=$(key_migrations)
K_BACK=$(key_backend) K_FRONT=$(key_frontend)
need() { [ "$(running_key "$1")" != "$2" ]; }
mark() { printf '%s %s\n' "$2" "$SHA" > "$STATE/$1"; }
DO_BDEPS=0 DO_FDEPS=0 DO_BUILD=0 DO_MIG=0 DO_API=0 DO_WEB=0
{ need backend-deps "$K_BDEPS" || [ ! -x "$APP/backend/.venv/bin/python" ]; } && DO_BDEPS=1
{ need frontend-deps "$K_FDEPS" || [ ! -d "$APP/frontend/node_modules" ]; } && DO_FDEPS=1
{ need frontend "$K_FRONT" || [ ! -f "$WEBDIR/.next/BUILD_ID" ]; } && DO_BUILD=1 DO_WEB=1
need migrations "$K_MIG" && DO_MIG=1
need backend "$K_BACK" && DO_API=1
plan=()
[ "$DO_BDEPS" = 1 ] && plan+=("backend-deps")
[ "$DO_FDEPS" = 1 ] && plan+=("frontend-deps")
[ "$DO_BUILD" = 1 ] && plan+=("frontend-build")
[ "$DO_MIG" = 1 ] && plan+=("migration-check")
[ "$DO_API" = 1 ] && plan+=("api-restart")
[ "$DO_WEB" = 1 ] && plan+=("web-restart")
note "to do: ${plan[*]:-nothing (no app code changed)}"

for f in api.env web.env postgres.env; do [ -s "$SECRETS/$f" ] || die "missing $SECRETS/$f"; done
# Without it the frontend falls back to its development default (:4000), which on this host is
# not this API.
grep -qE '^API_BASE_URL=http://127\.0\.0\.1:4100/?$' "$SECRETS/web.env" || die "$SECRETS/web.env must set API_BASE_URL=http://127.0.0.1:4100"
grep -qE '^NEXT_PUBLIC_SITE_URL=https?://.+' "$SECRETS/web.env" || die "$SECRETS/web.env must set NEXT_PUBLIC_SITE_URL"
# Sign-in is Better Auth in the web app (docs/deployment.md, "Sign-in"): its database role and
# secret, and the token it and the API share. Checked before anything changes.
for name in AUTH_DATABASE_URL BETTER_AUTH_SECRET AUTH_INTERNAL_TOKEN; do
  grep -qE "^$name=.+" "$SECRETS/web.env" || die "$SECRETS/web.env must set $name (docs/deployment.md, \"Sign-in\")"
done
[ -n "$(env_value AUTH_INTERNAL_TOKEN api.env)" ] && [ "$(env_value AUTH_INTERNAL_TOKEN api.env)" = "$(env_value AUTH_INTERNAL_TOKEN web.env)" ] \
  || die "AUTH_INTERNAL_TOKEN must be set, and the same, in $SECRETS/api.env and web.env"
systemctl is-active --quiet aichat-postgres || die "aichat-postgres is not running"
if [ "$DO_BDEPS$DO_FDEPS$DO_BUILD" != 000 ]; then preflight_resources; fi

# ---------------------------------------------------------------- 3. installs and the build (nothing restarts yet)
VENV="$APP/backend/.venv"
if [ "$DO_BDEPS" = 1 ]; then
  step "backend dependencies (requirements.lock)"
  [ -x "$VENV/bin/python" ] || build_step python3.12 -m venv "$VENV"
  build_step "$VENV/bin/python" -m pip install -q --require-hashes -r "$APP/backend/requirements.lock" || die "pip install failed; nothing was restarted"
  "$VENV/bin/python" -m pip check >/dev/null || die "the backend dependencies are inconsistent (pip check); nothing was restarted"
  mark backend-deps "$K_BDEPS"
  DONE+=("backend-deps")
fi
export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
if [ "$DO_FDEPS$DO_BUILD" != 00 ]; then ensure_node "$APP"; ensure_bun "$APP"; fi
NODE_BIN=$(node_bin_of "$APP")
if [ "$DO_FDEPS" = 1 ]; then
  step "frontend dependencies (package.json / bun.lock)"
  (cd "$APP/frontend" && PATH="$NODE_BIN:$PATH" build_step "$BUN" install --frozen-lockfile) || die "bun install failed; nothing was restarted"
  mark frontend-deps "$K_FDEPS"
  DONE+=("frontend-deps")
fi
if [ "$DO_FDEPS$DO_BUILD" != 00 ]; then
  # bun unpacks packages world-writable (0666), and they are code the web app runs and serves:
  # writable by root only. Idempotent, so it also fixes an install made before this line existed.
  chmod -R go-w "$APP/frontend/node_modules" 2>/dev/null || true
fi
NEW_BUILD=""
if [ "$DO_BUILD" = 1 ]; then
  if [ "$(cat "$WEBDIR/.next-prev/AICHAT_KEY" 2>/dev/null)" = "$K_FRONT" ]; then
    step "frontend: the build it replaced last time is this code: reusing it (no build)"
    NEW_BUILD=.next-prev
  else
    step "frontend build (beside the build being served; Next's cache kept in .next-cache)"
    # The served build's generated route types describe its own pages, and tsconfig includes them: a page
    # this commit removes would fail the new build's typecheck. Next uses them only to typecheck, never
    # to serve, so the served build keeps working without them.
    rm -rf "$WEBDIR/.next/types"
    rm -rf "$WEBDIR/.next-build"
    mkdir -p "$WEBDIR/.next-cache" "$WEBDIR/.next-build"
    ln -s ../.next-cache "$WEBDIR/.next-build/cache"
    (cd "$WEBDIR" && set -a && . "$SECRETS/web.env" && set +a \
      && NEXT_DIST_DIR=.next-build PATH="$NODE_BIN:$PATH" build_step "$BUN" run build) \
      || { rm -rf "$WEBDIR/.next-build"; die "the frontend build failed; the site keeps serving the previous build"; }
    printf '%s' "$K_FRONT" > "$WEBDIR/.next-build/AICHAT_KEY"
    # The build rewrites tracked files (Next adds its build directory to tsconfig.json): the
    # checkout stays exactly the commit.
    git -C "$APP" checkout -q -- .
    NEW_BUILD=.next-build
  fi
  DONE+=("frontend-build")
fi

# ---------------------------------------------------------------- 4. units
units=$(BACKUP_SUFFIX="$STAMP" bash "$TOOLS/deploy/server/install-units.sh" "$TOOLS") || die "could not install the systemd units"
if [ -n "$units" ]; then
  UNITS_CHANGED=1
  printf '%s\n' "$units"
  case "$units" in *"updated aichat-api.service"*) DO_API=1 ;; esac
  case "$units" in *"updated aichat-web.service"*) DO_WEB=1 ;; esac
fi

# ---------------------------------------------------------------- 5. migrations (only if new ones exist)
if [ "$DO_MIG" = 1 ]; then
  step "database migrations"
  status=$(systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
    -p WorkingDirectory="$APP/backend" "$VENV/bin/python" scripts/migration_status.py) || die "could not read the migration status"
  database=$(json_field database <<<"$status") head=$(json_field head <<<"$status")
  pending=$(json_field pending <<<"$status") known=$(json_field database_known <<<"$status")
  note "database: $database | this code: $head"
  if [ "$known" != True ]; then
    note "WARNING: the database is at a revision this code does not have (a rollback?). Continuing:"
    note "         migrations must be backward compatible (docs/deployment.md)."
  elif [ "$pending" != "[]" ]; then
    systemctl start aichat-pg-backup.service || die "the backup before migrating failed; nothing was migrated"
    backup=$(ls -1t /var/backups/aichat/aichat-*.dump 2>/dev/null | sed -n 1p)
    note "backup before migrating: $backup"
    systemd-run --pipe --wait --collect --quiet -p EnvironmentFile="$SECRETS/api.env" \
      -p WorkingDirectory="$APP/backend" "$VENV/bin/python" -m alembic upgrade head \
      || die "the migration failed (backup: $backup); the API was not restarted"
    note "migrated: $pending"
    DONE+=("migrated")
  else
    note "none pending"
  fi
  mark migrations "$K_MIG"
fi

# Before anything restarts: the web app's database role reaches its tables (role, password, and
# the grants of the migrations just run). Without it nobody could sign in after the restart.
step "sign-in database (AUTH_DATABASE_URL)"
auth_database_ok || die "the web app cannot reach its identity tables with AUTH_DATABASE_URL (role aichat_auth); nothing was restarted"

# ---------------------------------------------------------------- 6. restarts (only what changed)
if [ "$DO_API" = 1 ]; then
  step "backend: restart aichat-api"
  systemctl restart aichat-api
  wait_http "http://127.0.0.1:$API_PORT/ready" 90 || die "the API is not ready after its restart (journalctl -u aichat-api). Roll back: bun run rollback"
  [ "$(reported_release "http://127.0.0.1:$API_PORT/health")" = "$SHA" ] || die "the API does not report $SHA after its restart"
  mark backend "$K_BACK"
  DONE+=("api-restarted")
fi
if [ "$DO_WEB" = 1 ]; then
  step "frontend: restart aichat-web${NEW_BUILD:+ on the new build}"
  systemctl stop aichat-web
  if [ -n "$NEW_BUILD" ]; then
    rm -rf "$WEBDIR/.next-old"
    if [ -d "$WEBDIR/.next" ]; then mv "$WEBDIR/.next" "$WEBDIR/.next-old"; fi
    mv "$WEBDIR/$NEW_BUILD" "$WEBDIR/.next"
  fi
  systemctl start aichat-web
  if wait_http "http://127.0.0.1:$WEB_PORT/login" 120 && [ "$(reported_release "http://127.0.0.1:$WEB_PORT/api/health")" = "$SHA" ]; then
    if [ -n "$NEW_BUILD" ]; then
      rm -rf "$WEBDIR/.next-prev"
      if [ -d "$WEBDIR/.next-old" ]; then mv "$WEBDIR/.next-old" "$WEBDIR/.next-prev"; fi
    fi
    mark frontend "$K_FRONT"
    DONE+=("web-restarted")
  else
    if [ -n "$NEW_BUILD" ] && [ -d "$WEBDIR/.next-old" ]; then
      systemctl stop aichat-web
      rm -rf "$WEBDIR/.next-failed" && mv "$WEBDIR/.next" "$WEBDIR/.next-failed" && mv "$WEBDIR/.next-old" "$WEBDIR/.next"
      systemctl start aichat-web
      wait_http "http://127.0.0.1:$WEB_PORT/login" 120 || true
      die "the new frontend did not start; the previous build is serving again (journalctl -u aichat-web)"
    fi
    die "the web app did not start (journalctl -u aichat-web)"
  fi
fi

# ---------------------------------------------------------------- 7. smoke
step "smoke check"
systemctl is-active --quiet aichat-api || die "aichat-api is not running"
systemctl is-active --quiet aichat-web || die "aichat-web is not running"
wait_http "http://127.0.0.1:$API_PORT/ready" 30 || die "API /ready fails (database?)"
curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$API_PORT/health" || die "API /health fails"
wait_http "http://127.0.0.1:$WEB_PORT/login" 30 || die "web /login fails"
web_auth_ok "$WEB_PORT" || die "the web app reports its sign-in database unavailable (/api/health)"
check_chain "$WEB_PORT" aichat-api || die "web -> API -> database fails"
note "aichat-api and aichat-web active; /health, /ready and /login answer"

# ---------------------------------------------------------------- 8. record
# A rollback does not overwrite "previous": `bun run rollback` twice stays on the same commit
# (name a commit to go further back: HISTORY lists them).
if [ "${AICHAT_MODE:-deploy}" != rollback ] && [ -n "$PREV" ] && [ "$PREV" != "$SHA" ]; then printf '%s\n' "$PREV" > "$STATE/previous"; fi
printf '%s\n' "$SHA" > "$STATE/deployed"
printf '%s %s %s (previous %s) by %s (ssh %s): %s; %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$([ "${AICHAT_MODE:-deploy}" = rollback ] && echo "rolled back to" || echo deployed)" "$SHA" "${PREV:-none}" \
  "${AICHAT_OPERATOR:-unknown}" "${AICHAT_SSH_CLIENT:-local}" "${DONE[*]:-nothing to rebuild or restart}" "$(took)" >> "$HISTORY"
step "done: $SHA (${DONE[*]:-nothing to rebuild or restart})"
