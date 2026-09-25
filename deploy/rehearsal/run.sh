#!/usr/bin/env bash
#
# Rehearse the unified release model on a throwaway systemd host (Docker). Local only.
#
#   bun run rehearse          (needs Docker and a clean working tree; ~45 min: builds ~10 releases)
#   REHEARSAL_KEEP=1 ...      keep the container afterwards for inspection
#
# Drives the REAL deploy/deploy.sh, rollback.sh and status.sh over SSH against a host prepared by
# the real deploy/install.sh. Test commits are made in a temporary worktree and pushed to a
# temporary local "main"; nothing is pushed anywhere else. Rehearsal mode cannot reach the
# production host (deploy.sh refuses it, and requires the /etc/aichat/REHEARSAL marker).
#
# Proves: frontend-only / backend-only / both-halves changes each become ONE release with both
# halves; a broken frontend build and a broken backend never switch production; a failed live
# check rolls back automatically; manual rollback returns both halves to the exact previous
# release and a second rollback goes further back; migration guards; no bypass (unpushed or
# older commits, hand-run scripts, tampered releases, missing API_BASE_URL, low disk, the
# production host); a deploy survives its SSH connection being killed; and a poller on the
# host never sees the web app and the API report different releases at the same moment.
set -uo pipefail

REPO=$(git rev-parse --show-toplevel)
cd "$REPO" || exit 1
[ -z "$(git status --porcelain)" ] || { echo "rehearse needs a clean working tree (it deploys commits)" >&2; exit 1; }
command -v docker >/dev/null || { echo "rehearse needs Docker" >&2; exit 1; }
export MSYS_NO_PATHCONV=1
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

WORK=$(mktemp -d)
NAME=aichat-rehearsal
PORT=${REHEARSAL_SSH_PORT:-2222}
SOURCE="$WORK/source.git"
WT="$WORK/worktree"
# On Windows, the paths git is given must mean the same directory to git and to bash (with
# MSYS_NO_PATHCONV, native git reads /tmp/... as C:\tmp\...). WORK itself stays POSIX: it is on PATH.
if command -v cygpath >/dev/null; then SOURCE=$(cygpath -m "$SOURCE"); WT=$(cygpath -m "$WT"); fi
LOGS="$WORK/logs"
mkdir -p "$LOGS" "$WORK/ctx" "$WORK/bin"
RESULTS=()
pass() { RESULTS+=("PASS  $*"); printf '\033[32mPASS\033[0m  %s\n' "$*"; }
fail() { RESULTS+=("FAIL  $*"); printf '\033[31mFAIL\033[0m  %s\n' "$*"; }
step() { printf '\n\033[1m##### %s\033[0m\n' "$*"; }

cleanup() {
  git worktree remove --force "$WT" >/dev/null 2>&1 || true
  git worktree prune >/dev/null 2>&1 || true
  git update-ref -d refs/deploy/main >/dev/null 2>&1 || true
  if [ "${REHEARSAL_KEEP:-0}" != 1 ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; fi
  echo "logs: $LOGS"
}
trap cleanup EXIT

# ------------------------------------------------------------------ host
step "rehearsal host (Ubuntu 24.04, systemd, PostgreSQL + pgvector, SSH)"
ssh-keygen -q -t ed25519 -N "" -f "$WORK/key" -C rehearsal
cp deploy/rehearsal/Dockerfile deploy/rehearsal/docker-stub deploy/rehearsal/docker.service "$WORK/ctx/"
cp "$WORK/key.pub" "$WORK/ctx/authorized_keys"
docker build -q -t aichat-rehearsal:systemd --build-arg "BUN_VERSION=$(tr -d '[:space:]' < .bun-version)" "$(native "$WORK/ctx")" >/dev/null \
  || { echo "image build failed" >&2; exit 1; }
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  --tmpfs /run --tmpfs /run/lock -p "127.0.0.1:$PORT:22" aichat-rehearsal:systemd >/dev/null
docker exec "$NAME" systemctl is-system-running --wait >/dev/null 2>&1
docker exec "$NAME" bash -c 'for i in $(seq 30); do pg_isready -q -h 127.0.0.1 && break; sleep 1; done
  su postgres -c "psql -qc \"create role aichat login superuser password '"'"'rehearsal'"'"'\"" && su postgres -c "createdb -O aichat aichat"'
REAL_SSH=$(command -v ssh)
cat > "$WORK/ssh_config" <<EOF
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

step "prepare the host with the real deploy/install.sh (dummy secrets, never real ones)"
ssh rehearsal 'bash -s' <<'EOF'
set -e
umask 077
printf 'POSTGRES_USER=aichat\nPOSTGRES_PASSWORD=rehearsal\nPOSTGRES_DB=aichat\nBACKUP_DIR=/var/backups/aichat\nKEEP_DAYS=30\n' > /etc/aichat/postgres.env
cat > /etc/aichat/api.env <<E
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
git archive --format=tar HEAD | ssh rehearsal 'rm -rf /root/setup && mkdir -p /root/setup && tar -xf - -C /root/setup'
# Production's database is its own unit (aichat-postgres); stop the stand-in so install.sh starts it that way.
ssh rehearsal 'systemctl stop postgresql'
ssh rehearsal 'bash /root/setup/deploy/install.sh' > "$LOGS/install.log" 2>&1 && pass "install.sh prepared a fresh host" || fail "install.sh (see $LOGS/install.log)"

# Poller: the release each app reports, every 0.2 s, for the whole rehearsal.
ssh rehearsal 'bash -s' <<'EOF'
cat > /root/poll.sh <<'P'
rel() { curl -fsS --max-time 2 "$1" 2>/dev/null | python3.12 -c 'import json,sys; print(json.load(sys.stdin).get("release") or "-")' 2>/dev/null || echo -; }
while true; do echo "$(date +%s.%N) $(rel http://127.0.0.1:4100/health) $(rel http://127.0.0.1:3000/api/health)"; sleep 0.2; done
P
systemd-run --unit=rehearsal-poller --quiet -p StandardOutput=file:/root/poll.log -p StandardError=journal bash /root/poll.sh
EOF

# ------------------------------------------------------------------ helpers
git init -q --bare "$SOURCE"
git worktree add -q --detach "$WT" HEAD
G=(git -C "$WT" -c user.name=Rehearsal -c user.email=rehearsal@example.invalid -c core.autocrlf=false)
advance() { # message, then an edit command run inside the worktree; prints the new main
  local message=$1; shift
  (cd "$WT" && "$@")
  "${G[@]}" add -A && "${G[@]}" commit -q -m "rehearsal: $message" && git -C "$WT" push -q -f "$SOURCE" HEAD:refs/heads/main
  git -C "$WT" rev-parse HEAD
}
deploy() { DEPLOY_REHEARSAL=1 DEPLOY_REHEARSAL_SOURCE="$SOURCE" bash deploy/deploy.sh --yes "$@"; }
rollback() { bash deploy/rollback.sh --yes "$@"; }
live() { ssh rehearsal 'r=$(readlink -e /opt/aichat/current 2>/dev/null) && case "$r" in /opt/aichat/releases/*) basename "$r" ;; esac'; }
status_ok_on() { # the invariant holds, on release $1
  bash deploy/status.sh > "$LOGS/status-$2.log" 2>&1 && grep -q "INVARIANT OK: frontend and backend both run release $1" "$LOGS/status-$2.log"
}
schema() { ssh rehearsal "su postgres -c \"psql -d aichat -tAc 'select version_num from alembic_version'\""; }
short() { printf '%s' "${1:0:7}"; }

# ------------------------------------------------------------------ scenarios
git -C "$WT" push -q -f "$SOURCE" HEAD:refs/heads/main
R1=$(git -C "$WT" rev-parse HEAD)
step "S0 first release: $(short "$R1")"
# A new host's database is empty, so its first release has every migration pending.
deploy --with-migrations > "$LOGS/s0.log" 2>&1 && status_ok_on "$R1" s0 && pass "S0 first release live (empty database migrated after a backup); frontend == backend == $(short "$R1")" || fail "S0 first release (see $LOGS/s0.log)"

step "S1 frontend-only change"
R2=$(advance "frontend-only change" sh -c 'printf "\n// rehearsal: frontend-only change\n" >> frontend/apps/app/src/lib/brand.ts')
deploy > "$LOGS/s1.log" 2>&1 && status_ok_on "$R2" s1 && pass "S1 frontend-only commit -> one release; backend runs it too ($(short "$R2"))" || fail "S1 (see $LOGS/s1.log)"

step "S2 backend-only change"
R3=$(advance "backend-only change" sh -c 'printf "\n# rehearsal: backend-only change\n" >> backend/app/errors.py')
deploy > "$LOGS/s2.log" 2>&1 && status_ok_on "$R3" s2 && pass "S2 backend-only commit -> one release; frontend runs it too ($(short "$R3"))" || fail "S2 (see $LOGS/s2.log)"

step "S3 frontend + backend change"
R4=$(advance "frontend + backend change" sh -c 'printf "\n// rehearsal: both\n" >> frontend/apps/app/src/lib/brand.ts && printf "\n# rehearsal: both\n" >> backend/app/errors.py')
deploy > "$LOGS/s3.log" 2>&1 && status_ok_on "$R4" s3 && pass "S3 one commit changing both halves -> both live together ($(short "$R4"))" || fail "S3 (see $LOGS/s3.log)"

step "S4 broken frontend build"
BAD=$(advance "broken frontend build" sh -c 'printf "\nexport const broken: number = ;\n" >> frontend/apps/app/src/lib/brand.ts')
if ! deploy > "$LOGS/s4.log" 2>&1 && [ "$(live)" = "$R4" ] && status_ok_on "$R4" s4; then pass "S4 broken frontend build: deploy stopped, $(short "$R4") still live, invariant holds"; else fail "S4 (see $LOGS/s4.log)"; fi
advance "revert the broken frontend" "${G[@]}" revert --no-edit --no-commit "$BAD" >/dev/null

step "S5 broken backend (API cannot start)"
BAD=$(advance "broken backend" sh -c 'printf "\nraise RuntimeError(\"rehearsal: broken backend\")\n" >> backend/app/main.py')
if ! deploy > "$LOGS/s5.log" 2>&1 && grep -q "trial API not ready" "$LOGS/s5.log" && [ "$(live)" = "$R4" ] && status_ok_on "$R4" s5; then
  pass "S5 broken backend: stopped at the trial copies, $(short "$R4") still live"
else fail "S5 (see $LOGS/s5.log)"; fi
advance "revert the broken backend" "${G[@]}" revert --no-edit --no-commit "$BAD" >/dev/null

step "S6 release that passes its trial copies but fails live (web starts on the wrong port)"
BAD=$(advance "fails after the switch" sh -c 'sed -i "s/next start -p 3000/next start -p 3002/" frontend/apps/app/package.json')
if ! deploy > "$LOGS/s6.log" 2>&1 && grep -q "production is back on $R4" "$LOGS/s6.log" && [ "$(live)" = "$R4" ] && status_ok_on "$R4" s6; then
  pass "S6 failed live check: rolled back automatically to $(short "$R4"); invariant holds"
else fail "S6 (see $LOGS/s6.log)"; fi
R5=$(advance "revert the bad start script" "${G[@]}" revert --no-edit --no-commit "$BAD")

step "S7 manual rollback, twice"
if rollback > "$LOGS/s7a.log" 2>&1 && status_ok_on "$R3" s7a; then pass "S7 rollback: frontend and backend both back on the exact previous release $(short "$R3")"; else fail "S7 first rollback (see $LOGS/s7a.log)"; fi
if rollback > "$LOGS/s7b.log" 2>&1 && status_ok_on "$R2" s7b; then pass "S7 second rollback goes further back ($(short "$R2")), never forward to $(short "$R4")"; else fail "S7 second rollback (see $LOGS/s7b.log)"; fi
deploy > "$LOGS/s7c.log" 2>&1 && status_ok_on "$R5" s7c && pass "S7 deploy after rollbacks: main tip $(short "$R5") live" || fail "S7 redeploy (see $LOGS/s7c.log)"

step "S8 migration guards"
HEAD_REVISION=$(grep -h '^revision = ' "$WT"/backend/alembic/versions/*.py | cut -d'"' -f2 | sort | tail -1)
cat > "$WT/backend/alembic/versions/0099_rehearsal.py" <<M
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
MIG=$(advance "backward-compatible migration" true)
if ! deploy > "$LOGS/s8a.log" 2>&1 && grep -q "pending migrations" "$LOGS/s8a.log" && [ "$(live)" = "$R5" ] && [ "$(schema)" != 0099_rehearsal ]; then
  pass "S8 pending migration without --with-migrations: refused, nothing migrated, $(short "$R5") live"
else fail "S8 refusal (see $LOGS/s8a.log)"; fi
if deploy --with-migrations > "$LOGS/s8b.log" 2>&1 && grep -q "backup before migrating: /var/backups/aichat/aichat-" "$LOGS/s8b.log" && [ "$(schema)" = 0099_rehearsal ] && status_ok_on "$MIG" s8b; then
  pass "S8 --with-migrations: backup taken, migrated to 0099, $(short "$MIG") live"
else fail "S8 migrate (see $LOGS/s8b.log)"; fi
if ! rollback > "$LOGS/s8c.log" 2>&1 && grep -q "is newer than release" "$LOGS/s8c.log" && [ "$(live)" = "$MIG" ]; then
  pass "S8 rollback past the migration refused without --allow-older-schema"
else fail "S8 rollback guard (see $LOGS/s8c.log)"; fi
if rollback --allow-older-schema > "$LOGS/s8d.log" 2>&1 && status_ok_on "$R5" s8d; then pass "S8 with --allow-older-schema: back on $(short "$R5") (schema stays 0099)"; else fail "S8 older-schema rollback (see $LOGS/s8d.log)"; fi

step "S9 no bypass"
UNPUSHED=$( (cd "$WT" && printf '\n// never pushed\n' >> frontend/apps/app/src/lib/brand.ts) && "${G[@]}" commit -qam unpushed && git -C "$WT" rev-parse HEAD)
if ! deploy --ref "$UNPUSHED" > "$LOGS/s9a.log" 2>&1 && grep -q "is not a commit of main" "$LOGS/s9a.log"; then pass "S9 a commit that is not on main is refused"; else fail "S9 unpushed (see $LOGS/s9a.log)"; fi
"${G[@]}" reset -q --hard HEAD~1
if ! deploy --ref "$R2" > "$LOGS/s9b.log" 2>&1 && grep -q "is older than main" "$LOGS/s9b.log"; then pass "S9 an older commit without --older is refused"; else fail "S9 older (see $LOGS/s9b.log)"; fi
if ! ssh rehearsal "bash /opt/aichat/releases/$R5/deploy/server/release.sh $R5" > "$LOGS/s9c.log" 2>&1 && grep -q "never run release.sh by hand" "$LOGS/s9c.log"; then pass "S9 running release.sh by hand is refused"; else fail "S9 hand-run (see $LOGS/s9c.log)"; fi
ssh rehearsal "printf '# tampered\n' >> /opt/aichat/releases/$MIG/backend/app/errors.py"
if ! rollback --to "$MIG" --allow-older-schema > "$LOGS/s9d.log" 2>&1 && grep -q "does not match its commit" "$LOGS/s9d.log" && [ "$(live)" = "$R5" ]; then pass "S9 a tampered release is refused (files checked against the commit)"; else fail "S9 tampered (see $LOGS/s9d.log)"; fi
ssh rehearsal "sed -i 's#^API_BASE_URL=.*#API_BASE_URL=http://127.0.0.1:4000#' /etc/aichat/web.env"
R6=$(advance "harmless change" sh -c 'printf "\n// rehearsal: harmless\n" >> frontend/apps/app/src/lib/brand.ts')
if ! deploy > "$LOGS/s9e.log" 2>&1 && grep -q "must set API_BASE_URL" "$LOGS/s9e.log" && [ "$(live)" = "$R5" ]; then pass "S9 a web.env without API_BASE_URL=:4100 is refused"; else fail "S9 API_BASE_URL (see $LOGS/s9e.log)"; fi
ssh rehearsal "sed -i 's#^API_BASE_URL=.*#API_BASE_URL=http://127.0.0.1:4100#' /etc/aichat/web.env"
if ! ssh rehearsal "AICHAT_MIN_FREE_MB=999999999 bash -c '. /opt/aichat/current/deploy/server/lib.sh; preflight_resources'" > "$LOGS/s9f.log" 2>&1 && grep -q "MB free on" "$LOGS/s9f.log"; then pass "S9 too little disk is refused before any build"; else fail "S9 low disk (see $LOGS/s9f.log)"; fi
if ! DEPLOY_REHEARSAL=1 DEPLOY_REHEARSAL_SOURCE="$SOURCE" DEPLOY_HOST=root@10.1.30.37 bash deploy/deploy.sh --yes > "$LOGS/s9g.log" 2>&1 && grep -q "never deploys to production" "$LOGS/s9g.log"; then pass "S9 rehearsal mode refuses the production host (before connecting)"; else fail "S9 production guard (see $LOGS/s9g.log)"; fi
if ! grep -qE '"deploy:|"rollback:|deploy-frontend|deploy-backend' package.json frontend/package.json frontend/apps/app/package.json; then pass "S9 no component-level deploy command exists"; else fail "S9 component deploy command found"; fi

step "S10 the SSH connection dies mid-deploy"
( deploy > "$LOGS/s10.log" 2>&1 ) &
DEPLOY_PID=$!
for _ in $(seq 1 900); do grep -q "3/4 validate" "$LOGS/s10.log" 2>/dev/null && break; sleep 1; done
# Kill both ends of the connection: the local deploy and the host-side client waiting on the
# unit (what a dropped SSH session does). The systemd unit itself must carry on.
kill "$DEPLOY_PID" 2>/dev/null
ssh rehearsal "pkill -f 'systemd-run --unit=aichat-deploy-${R6:0:12}'; pkill -f 'journalctl -f -n0 -o cat -u aichat-deploy-${R6:0:12}'" || true
ssh rehearsal "systemctl list-units 'aichat-deploy-*' --no-legend" > "$LOGS/s10-unit.log" 2>&1
for _ in $(seq 1 600); do [ "$(live)" = "$R6" ] && status_ok_on "$R6" s10 && break; sleep 2; done
if status_ok_on "$R6" s10; then pass "S10 killed the local deploy mid-way: the host finished it; $(short "$R6") live, invariant holds"; else fail "S10 (see $LOGS/s10.log)"; fi

step "poller: did the web app and the API ever report different releases at the same moment?"
ssh rehearsal 'systemctl stop rehearsal-poller; cat /root/poll.log' > "$LOGS/poll.log"
samples=$(awk '$2 != "-" && $3 != "-"' "$LOGS/poll.log" | wc -l)
mixed=$(awk '$2 != "-" && $3 != "-" && $2 != $3' "$LOGS/poll.log" | wc -l)
if [ "$mixed" = 0 ] && [ "$samples" -gt 100 ]; then pass "poller: $samples samples with both apps up, 0 with different releases"; else fail "poller: $mixed of $samples samples showed different releases"; fi
# Every stretch (after the first release) in which either app did not answer: the switches' outages.
echo "unavailable (seconds, one per switch or failed release): $(awk '{ up = ($2 != "-" && $3 != "-") }
  up { if (down) printf "%.1f ", $1 - down; down = 0; seen = 1; next }
  seen && !down { down = $1 }' "$LOGS/poll.log")"

step "result"
printf '%s\n' "${RESULTS[@]}"
if printf '%s\n' "${RESULTS[@]}" | grep '^FAIL' >/dev/null; then exit 1; fi
echo "ALL PASS"
