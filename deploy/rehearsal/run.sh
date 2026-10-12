#!/usr/bin/env bash
#
# Rehearse the production deploy (deploy/deploy.sh, rollback.sh, status.sh) on a throwaway
# systemd host (Docker). Local only, and never a deploy prerequisite.
#
#   bun run rehearse          (needs Docker and a clean working tree; ~30 min)
#   REHEARSAL_KEEP=1 ...      keep the container afterwards for inspection
#
# The host starts where production was before this deploy model: the release layout, prepared
# and deployed by the scripts of commit $OLD. Test commits are made in a temporary worktree and
# pushed to a temporary bare repository standing in for GitHub; nothing is pushed anywhere else.
# Rehearsal mode cannot reach the production host (deploy.sh refuses it, and the host must carry
# the /etc/aichat/REHEARSAL marker).
#
# Proves: the cutover from the release layout, and that a failed cutover puts it back; a
# frontend-only, backend-only, migration and full-stack commit each rebuild and restart only
# their part; a docs-only commit restarts nothing; a failed build never reaches users and never
# reports success; a rollback swaps the previous frontend build back without building; two
# deploys at once; the refusals (dirty tree, not GitHub main, the production host); database
# rows and secrets survive everything. Prints how long each deploy took.
set -uo pipefail

OLD=25029ea138e2e696d9d0822928d3cbbe4141dc20 # the last release of the release layout
REPO=$(git rev-parse --show-toplevel)
cd "$REPO" || exit 1
[ -z "$(git status --porcelain)" ] || { echo "rehearse needs a clean working tree (it deploys commits)" >&2; exit 1; }
command -v docker > /dev/null || { echo "rehearse needs Docker" >&2; exit 1; }
export MSYS_NO_PATHCONV=1
native() { if command -v cygpath > /dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

WORK=$(mktemp -d)
NAME=aichat-rehearsal
PORT=${REHEARSAL_SSH_PORT:-2222}
SOURCE="$WORK/source.git"
WT="$WORK/worktree"
WTOLD="$WORK/worktree-old"
# On Windows, the paths git is given must mean the same directory to git and to bash.
if command -v cygpath > /dev/null; then SOURCE=$(cygpath -m "$SOURCE"); WT=$(cygpath -m "$WT"); WTOLD=$(cygpath -m "$WTOLD"); fi
LOGS="$WORK/logs"
mkdir -p "$LOGS" "$WORK/ctx" "$WORK/bin"
RESULTS=() TIMES=()
pass() { RESULTS+=("PASS  $*"); printf '\033[32mPASS\033[0m  %s\n' "$*"; }
fail() { RESULTS+=("FAIL  $*"); printf '\033[31mFAIL\033[0m  %s\n' "$*"; }
step() { printf '\n\033[1m##### %s\033[0m\n' "$*"; }

cleanup() {
  git worktree remove --force "$WT" > /dev/null 2>&1 || true
  git worktree remove --force "$WTOLD" > /dev/null 2>&1 || true
  git worktree prune > /dev/null 2>&1 || true
  git for-each-ref --format='%(refname)' refs/deploy | while read -r ref; do git update-ref -d "$ref"; done 2> /dev/null || true
  if [ "${REHEARSAL_KEEP:-0}" != 1 ]; then docker rm -f "$NAME" > /dev/null 2>&1 || true; fi
  echo "logs: $LOGS"
}
trap cleanup EXIT

# ------------------------------------------------------------------ host
step "rehearsal host (Ubuntu 24.04, systemd, PostgreSQL + pgvector, SSH)"
ssh-keygen -q -t ed25519 -N "" -f "$WORK/key" -C rehearsal
cp deploy/rehearsal/Dockerfile deploy/rehearsal/docker-stub deploy/rehearsal/docker.service "$WORK/ctx/"
cp "$WORK/key.pub" "$WORK/ctx/authorized_keys"
docker build -q -t aichat-rehearsal:systemd --build-arg "BUN_VERSION=$(tr -d '[:space:]' < .bun-version)" "$(native "$WORK/ctx")" > /dev/null \
  || { echo "image build failed" >&2; exit 1; }
docker rm -f "$NAME" > /dev/null 2>&1
docker run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  --tmpfs /run --tmpfs /run/lock -p "127.0.0.1:$PORT:22" aichat-rehearsal:systemd > /dev/null
docker exec "$NAME" systemctl is-system-running --wait > /dev/null 2>&1
docker exec "$NAME" bash -c 'for i in $(seq 30); do pg_isready -q -h 127.0.0.1 && break; sleep 1; done
  su postgres -c "psql -qc \"create role aichat login superuser password '"'"'rehearsal'"'"'\"" && su postgres -c "createdb -O aichat aichat"'
REAL_SSH=$(command -v ssh)
cat > "$WORK/ssh_config" << EOF
Host rehearsal
  HostName 127.0.0.1
  Port $PORT
  User root
  IdentityFile $WORK/key
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
EOF
printf '#!/usr/bin/env bash\nexec "%s" -F "%s" "$@"\n' "$REAL_SSH" "$WORK/ssh_config" > "$WORK/bin/ssh"
chmod +x "$WORK/bin/ssh"
export PATH="$WORK/bin:$PATH"
export DEPLOY_HOST=rehearsal
ssh rehearsal true || { echo "ssh to the rehearsal host failed" >&2; exit 1; }

step "the release layout, as production had it: $OLD's install.sh and deploy.sh (dummy secrets)"
ssh rehearsal 'bash -s' << 'EOF'
set -e
umask 077
printf 'POSTGRES_USER=aichat\nPOSTGRES_PASSWORD=rehearsal\nPOSTGRES_DB=aichat\nBACKUP_DIR=/var/backups/aichat\nKEEP_DAYS=30\n' > /etc/aichat/postgres.env
cat > /etc/aichat/api.env << E
APP_ENV=production
SECRET_KEY=$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 60)
DATABASE_URL=postgresql+asyncpg://aichat:rehearsal@127.0.0.1:5432/aichat
TRUST_FORWARDED_FOR=true
EMAIL_BACKEND=ollastack
OLLASTACK_TOKEN=rehearsal-dummy
OLLASTACK_MAILBOX_ID=rehearsal
LLM_PROVIDER=openai_compatible
LLM_PRIMARY_BASE_URL=http://127.0.0.1:9/v1
LLM_PRIMARY_API_KEY=rehearsal-dummy
LLM_PRIMARY_MODEL=rehearsal
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=
E
printf 'API_BASE_URL=http://127.0.0.1:4100\nNEXT_PUBLIC_SITE_URL=https://rehearsal.invalid\nNEXT_PUBLIC_SENTRY_DSN=\n' > /etc/aichat/web.env
EOF
git archive --format=tar "$OLD" | ssh rehearsal 'rm -rf /root/setup && mkdir -p /root/setup && tar -xf - -C /root/setup'
ssh rehearsal 'systemctl stop postgresql' # production's database is its own unit (aichat-postgres)
ssh rehearsal 'bash /root/setup/deploy/install.sh' > "$LOGS/install.log" 2>&1 || { fail "old install.sh (see $LOGS/install.log)"; exit 1; }
git init -q --bare "$SOURCE"
git push -q "$SOURCE" "$OLD:refs/heads/main"
git worktree add -q --detach "$WTOLD" "$OLD"
mkdir -p "$WTOLD/.deploy/verified"
printf '{"version":1,"sha":"%s","tree":"%s","source":"local","rehearsal":true,"result":"success","log_sha256":"-","jobs":[{"name":"Backend (lint, contract, tests)","conclusion":"success"},{"name":"Frontend (typecheck, lint, tests incl. contract, build)","conclusion":"success"},{"name":"Integration (end-to-end)","conclusion":"success"}]}\n' \
  "$OLD" "$(git rev-parse "$OLD^{tree}")" > "$WTOLD/.deploy/verified/$OLD.json"
printf 'rehearsal\n' > "$WTOLD/.deploy/verified/$OLD.log"
(cd "$WTOLD" && DEPLOY_REHEARSAL=1 DEPLOY_REHEARSAL_SOURCE="$SOURCE" bash deploy/deploy.sh --yes --ref "$OLD" --with-migrations) > "$LOGS/old-layout.log" 2>&1
[ "$(ssh rehearsal 'readlink -f /opt/aichat/current')" = "/opt/aichat/releases/$OLD" ] \
  && pass "the release layout runs $OLD (as production did)" || { fail "old layout deploy (see $LOGS/old-layout.log)"; exit 1; }
# Data and secrets that must survive everything below.
ssh rehearsal "su postgres -c \"psql -d aichat -qc \\\"create table rehearsal_keep (note text); insert into rehearsal_keep values ('survives')\\\"\""
SECRETS_BEFORE=$(ssh rehearsal 'sha256sum /etc/aichat/*.env')

# ------------------------------------------------------------------ helpers
git worktree add -q --detach "$WT" HEAD
git -C "$WT" push -q -f "$SOURCE" HEAD:refs/heads/main
G=(git -C "$WT" -c user.name=Rehearsal -c user.email=rehearsal@example.invalid -c core.autocrlf=false)
advance() { # message, then an edit command run inside the worktree: commit it, push it to "GitHub" main, print it
  local message=$1; shift
  (cd "$WT" && "$@") > /dev/null
  "${G[@]}" add -A && "${G[@]}" commit -q -m "rehearsal: $message" && git -C "$WT" push -q -f "$SOURCE" HEAD:refs/heads/main
  git -C "$WT" rev-parse HEAD
}
in_wt() { (cd "$WT" && DEPLOY_REHEARSAL=1 DEPLOY_REHEARSAL_SOURCE="$SOURCE" bash "$@"); }
deploy() { in_wt deploy/deploy.sh "$@"; }
rollback() { in_wt deploy/rollback.sh "$@"; }
took() { sed -n 's/^Time: \([0-9]*\)s$/\1/p' "$1" | tail -1; }
pid() { ssh rehearsal "systemctl show -p MainPID --value $1"; }
build_id() { ssh rehearsal 'cat /opt/aichat/app/frontend/apps/app/.next/BUILD_ID 2>/dev/null'; }
reported() { ssh rehearsal "curl -fsS --max-time 5 $1 2>/dev/null | python3.12 -c 'import json,sys; print(json.load(sys.stdin)[\"release\"])' 2>/dev/null"; }
api_rel() { reported http://127.0.0.1:4100/health; }
web_rel() { reported http://127.0.0.1:3000/api/health; }
schema() { ssh rehearsal "su postgres -c \"psql -d aichat -tAc 'select version_num from alembic_version'\""; }
snap() { A=$(pid aichat-api) W=$(pid aichat-web) B=$(build_id); }
api_same() { [ "$(pid aichat-api)" = "$A" ]; }
web_same() { [ "$(pid aichat-web)" = "$W" ] && [ "$(build_id)" = "$B" ]; }
short() { printf '%s' "${1:0:7}"; }

# ------------------------------------------------------------------ the cutover
step "C0 cutover: a first deploy that fails puts the release layout back"
GOOD=$(git -C "$WT" rev-parse HEAD)
advance "a backend that cannot start" sed -i '1i raise RuntimeError("rehearsal: this backend cannot start")' backend/app/main.py > /dev/null
if ! deploy > "$LOGS/c0a.log" 2>&1 && grep -q "cutover failed: restoring" "$LOGS/c0a.log" \
  && [ "$(api_rel)" = "$OLD" ] && [ "$(web_rel)" = "$OLD" ] \
  && ssh rehearsal 'systemctl show -p ExecStart --value aichat-api' | grep -q /opt/aichat/current; then
  pass "C0 a failed cutover restored the release layout: both apps serve $(short "$OLD") again"
else fail "C0 failed cutover (see $LOGS/c0a.log)"; fi
git -C "$WT" reset -q --hard "$GOOD" && git -C "$WT" push -q -f "$SOURCE" HEAD:refs/heads/main

step "C0 cutover: release layout -> the checkout /opt/aichat/app"
if deploy > "$LOGS/c0b.log" 2>&1 && grep -q "Status: MATCH" "$LOGS/c0b.log" \
  && [ "$(api_rel)" = "$GOOD" ] && [ "$(web_rel)" = "$GOOD" ] \
  && [ "$(ssh rehearsal 'systemctl show -p WorkingDirectory --value aichat-api')" = /opt/aichat/app/backend ] \
  && [ "$(ssh rehearsal 'systemctl show -p WorkingDirectory --value aichat-web')" = /opt/aichat/app/frontend/apps/app ] \
  && ssh rehearsal "test -d /opt/aichat/releases/$OLD"; then
  pass "C0 cutover: both apps run $(short "$GOOD") from /opt/aichat/app; the old release is left in place"
else fail "C0 cutover (see $LOGS/c0b.log)"; fi
TIMES+=("cutover (full build after the failed attempt): $(took "$LOGS/c0b.log")s")

# ------------------------------------------------------------------ changed parts only
step "T1 frontend-only change: only the web app rebuilds and restarts"
snap
F1=$(advance "frontend-only" sh -c "printf '\n// rehearsal: frontend-only\n' >> frontend/apps/app/src/lib/brand.ts")
if deploy > "$LOGS/t1.log" 2>&1 && grep -q "to do: frontend-build web-restart$" "$LOGS/t1.log" && grep -q "Status: MATCH" "$LOGS/t1.log" \
  && api_same && [ "$(pid aichat-web)" != "$W" ] && [ "$(build_id)" != "$B" ] && [ "$(web_rel)" = "$F1" ] && [ "$(api_rel)" = "$GOOD" ]; then
  pass "T1 frontend-only: web rebuilt and restarted, the API untouched (still $(short "$GOOD"))"
else fail "T1 frontend-only (see $LOGS/t1.log)"; fi
TIMES+=("frontend-only: $(took "$LOGS/t1.log")s")

step "T2 backend-only change: only the API restarts"
snap
B1=$(advance "backend-only" sh -c "printf '\n# rehearsal: backend-only\n' >> backend/app/health.py")
if deploy > "$LOGS/t2.log" 2>&1 && grep -q "to do: api-restart$" "$LOGS/t2.log" && grep -q "Status: MATCH" "$LOGS/t2.log" \
  && web_same && [ "$(pid aichat-api)" != "$A" ] && [ "$(api_rel)" = "$B1" ] && [ "$(web_rel)" = "$F1" ]; then
  pass "T2 backend-only: the API restarted, the web app and its build untouched"
else fail "T2 backend-only (see $LOGS/t2.log)"; fi
TIMES+=("backend-only: $(took "$LOGS/t2.log")s")

step "docs-only change: nothing rebuilds or restarts"
snap
advance "docs-only" sh -c "printf '\nrehearsal: docs-only\n' >> docs/deployment.md" > /dev/null
if deploy > "$LOGS/docs.log" 2>&1 && grep -q "to do: nothing" "$LOGS/docs.log" && grep -q "Status: MATCH" "$LOGS/docs.log" && api_same && web_same; then
  pass "docs-only: nothing rebuilt or restarted; status MATCH"
else fail "docs-only (see $LOGS/docs.log)"; fi
TIMES+=("docs-only: $(took "$LOGS/docs.log")s")

step "T3 migration: backup, migrate, API restart; the web app untouched"
HEAD_REVISION=$(grep -h '^revision = ' "$WT"/backend/alembic/versions/*.py | cut -d'"' -f2 | sort | tail -1)
cat > "$WT/backend/alembic/versions/0099_rehearsal.py" << M
"""Rehearsal only: a backward-compatible migration (adds a table nothing uses)."""

import sqlalchemy as sa
from alembic import op

revision = "0099_rehearsal"
down_revision = "$HEAD_REVISION"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("rehearsal_marker", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    op.drop_table("rehearsal_marker")
M
snap
BACKUPS=$(ssh rehearsal 'ls /var/backups/aichat/*.dump 2>/dev/null | wc -l')
M1=$(advance "a migration" true)
if deploy > "$LOGS/t3.log" 2>&1 && grep -q "backup before migrating: /var/backups/aichat/" "$LOGS/t3.log" && grep -q "Status: MATCH" "$LOGS/t3.log" \
  && [ "$(schema)" = 0099_rehearsal ] && [ "$(ssh rehearsal 'ls /var/backups/aichat/*.dump 2>/dev/null | wc -l')" -gt "$BACKUPS" ] \
  && [ "$(api_rel)" = "$M1" ] && web_same; then
  pass "T3 migration: backup taken, migrated to 0099, the API restarted, the web app untouched"
else fail "T3 migration (see $LOGS/t3.log)"; fi
TIMES+=("migration (backend): $(took "$LOGS/t3.log")s")

step "T4 full-stack change: both update, both run the same commit"
snap
FS=$(advance "full-stack" sh -c "printf '\n// rehearsal: both\n' >> frontend/apps/app/src/lib/brand.ts && printf '\n# rehearsal: both\n' >> backend/app/health.py")
if deploy > "$LOGS/t4.log" 2>&1 && grep -q "Status: MATCH" "$LOGS/t4.log" \
  && [ "$(pid aichat-api)" != "$A" ] && [ "$(pid aichat-web)" != "$W" ] && [ "$(build_id)" != "$B" ] \
  && [ "$(api_rel)" = "$FS" ] && [ "$(web_rel)" = "$FS" ]; then
  pass "T4 full-stack: API and web restarted; both report $(short "$FS")"
else fail "T4 full-stack (see $LOGS/t4.log)"; fi
TIMES+=("full-stack: $(took "$LOGS/t4.log")s")

step "T5 a failed frontend build never reaches users and never reports success"
snap
advance "a frontend that does not build" sh -c "printf '\nexport const broken = ;\n' >> frontend/apps/app/src/lib/brand.ts" > /dev/null
if ! deploy > "$LOGS/t5a.log" 2>&1 && grep -q "the frontend build failed" "$LOGS/t5a.log" && grep -q "Status: MISMATCH" "$LOGS/t5a.log" \
  && web_same && api_same && [ "$(web_rel)" = "$FS" ] && ssh rehearsal 'curl -fsS -o /dev/null http://127.0.0.1:3000/login'; then
  pass "T5 failed build: exit non-zero, MISMATCH, the previous build keeps serving"
else fail "T5 failed build (see $LOGS/t5a.log)"; fi
FIX=$(advance "fix the frontend" git checkout HEAD~1 -- frontend/apps/app/src/lib/brand.ts)
if deploy > "$LOGS/t5b.log" 2>&1 && grep -q "Status: MATCH" "$LOGS/t5b.log" && web_same; then
  pass "T5 the fix deploys: its frontend is the one being served, so nothing is rebuilt"
else fail "T5 fix (see $LOGS/t5b.log)"; fi

step "T6 rollback: the previous frontend build is swapped back without building"
F2=$(advance "frontend change before a rollback" sh -c "printf '\n// rehearsal: before a rollback\n' >> frontend/apps/app/src/lib/brand.ts")
deploy > "$LOGS/t6a.log" 2>&1 || fail "T6 deploy before the rollback (see $LOGS/t6a.log)"
snap
if rollback > "$LOGS/t6b.log" 2>&1 && grep -q "reusing it (no build)" "$LOGS/t6b.log" && grep -q "Status: MISMATCH (the production checkout is not GitHub main)" "$LOGS/t6b.log" \
  && api_same && [ "$(pid aichat-web)" != "$W" ] && [ "$(web_rel)" = "$FIX" ]; then
  pass "T6 rollback to $(short "$FIX"): frontend swapped back without a build; status says production is not GitHub main"
else fail "T6 rollback (see $LOGS/t6b.log)"; fi
TIMES+=("rollback (frontend swap): $(took "$LOGS/t6b.log")s")
if deploy > "$LOGS/t6c.log" 2>&1 && grep -q "reusing it (no build)" "$LOGS/t6c.log" && grep -q "Status: MATCH" "$LOGS/t6c.log" && [ "$(web_rel)" = "$F2" ]; then
  pass "T6 deploying main again: back on $(short "$F2") by a swap, MATCH"
else fail "T6 redeploy (see $LOGS/t6c.log)"; fi

# ------------------------------------------------------------------ safety
step "two deploys at once: the second one stops cleanly"
advance "concurrent deploys" sh -c "printf '\n// rehearsal: concurrent\n' >> frontend/apps/app/src/lib/brand.ts" > /dev/null
(deploy > "$LOGS/cc-a.log" 2>&1; echo $? > "$LOGS/cc-a.rc") &
sleep 8
deploy > "$LOGS/cc-b.log" 2>&1; echo $? > "$LOGS/cc-b.rc"
wait
if [ "$(cat "$LOGS/cc-a.rc")" = 0 ] && [ "$(cat "$LOGS/cc-b.rc")" != 0 ] && grep -q "another deploy is running" "$LOGS/cc-b.log" && grep -q "Status: MATCH" "$LOGS/cc-a.log"; then
  pass "two deploys at once: the first finished (MATCH), the second stopped: another deploy is running"
else fail "concurrent deploys (see $LOGS/cc-a.log and $LOGS/cc-b.log)"; fi

step "refusals"
touch "$WT/stray.txt"
! deploy > "$LOGS/r1.log" 2>&1 && grep -q "uncommitted or untracked" "$LOGS/r1.log" && pass "a dirty tree is refused" || fail "dirty tree (see $LOGS/r1.log)"
rm -f "$WT/stray.txt"
(cd "$WT" && printf '\n// never pushed\n' >> frontend/apps/app/src/lib/brand.ts) && "${G[@]}" commit -qam "not pushed"
! deploy > "$LOGS/r2.log" 2>&1 && grep -q "is not GitHub main" "$LOGS/r2.log" && pass "a commit that is not GitHub main is refused" || fail "not main (see $LOGS/r2.log)"
git -C "$WT" reset -q --hard HEAD~1
! DEPLOY_HOST=root@10.1.50.94 deploy > "$LOGS/r3.log" 2>&1 && grep -q "never deploys to production" "$LOGS/r3.log" && pass "rehearsal mode refuses the production host" || fail "production host (see $LOGS/r3.log)"

step "data and secrets survived everything"
[ "$(ssh rehearsal "su postgres -c \"psql -d aichat -tAc 'select note from rehearsal_keep'\"")" = survives ] && pass "database rows survived the cutover and every deploy" || fail "database rows"
[ "$(ssh rehearsal 'sha256sum /etc/aichat/*.env')" = "$SECRETS_BEFORE" ] && pass "secrets untouched" || fail "secrets changed"
in_wt deploy/status.sh > "$LOGS/status.log" 2>&1 && grep -q "Status: MATCH" "$LOGS/status.log" && grep -q "ok    no local edits in the checkout" "$LOGS/status.log" \
  && pass "bun run status: healthy, no local edits in the checkout, MATCH" || fail "status (see $LOGS/status.log)"

step "result"
printf '%s\n' "${RESULTS[@]}"
echo
echo "deploy times (deploy.sh's own clock, rehearsal host on this machine):"
printf '  %s\n' "${TIMES[@]}"
if printf '%s\n' "${RESULTS[@]}" | grep '^FAIL' > /dev/null; then exit 1; fi
echo "ALL PASS"
