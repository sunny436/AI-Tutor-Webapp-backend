#!/usr/bin/env bash
#
# Provision a fresh Ubuntu 24.04 host into a running Ayurveda deployment.
#
#   sudo bash deploy/install.sh
#
# IDEMPOTENT. Safe to re-run after every change: it installs what is missing,
# pulls what exists, re-renders units, and never touches secrets or data.
#
# It deliberately does NOT create /etc/ayurveda/*.env. Secrets come from your
# password manager, not from a script in git. The script stops and tells you
# which files are missing rather than inventing empty ones that would fail
# later in a confusing way.
#
# What it does not do: import data. That is a separate, deliberate step, so a
# re-run can never overwrite a live database. See deploy/README.md.
set -euo pipefail

REPO_ROOT="/opt/ayurveda"
# SSH, not HTTPS: both repositories are private, and an unattended host has no
# way to answer a username prompt. Each URL uses a Host alias from
# /root/.ssh/config so it presents its own read-only DEPLOY KEY - a GitHub
# deploy key is valid for exactly one repository, so they cannot share one.
#
# Set up once per machine (see deploy/README.md):
#   ssh-keygen -t ed25519 -f /root/.ssh/deploy_backend  -N ""
#   ssh-keygen -t ed25519 -f /root/.ssh/deploy_frontend -N ""
# then add each .pub to the matching repo under Settings -> Deploy keys,
# WITHOUT write access.
BACKEND_REPO="git@github-backend:akshat948/Ayurveda-Backend-.git"
FRONTEND_REPO="git@github-frontend:akshat948/ayurveda-frontend.git"
SECRETS_DIR="/etc/ayurveda"
BUN="/root/.bun/bin/bun"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

log "1/8  packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl git jq \
  docker.io docker-compose-v2 \
  tesseract-ocr \
  python3 python3-venv python3-pip
systemctl enable --now docker

# Swap. The box has 3.8 GB and the Python backend peaks near 2 GB loading its
# embedding model; `next build` wants another 1-2 GB. Without swap a build and
# a running backend cannot coexist.
if ! swapon --show | grep -q .; then
  log "1b/8  swap (4G)"
  fallocate -l 4G /swapfile && chmod 600 /swapfile
  mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

log "2/8  node + bun"
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; apt-get install -y -qq nodejs; }
[ -x "$BUN" ] || curl -fsSL https://bun.sh/install | bash
export PATH="/root/.bun/bin:$PATH"

log "3/8  cloudflared"
command -v cloudflared >/dev/null || {
  curl -fsSL -o /tmp/cf.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i /tmp/cf.deb
}

log "4/8  repositories"
mkdir -p "$REPO_ROOT"
for k in deploy_backend deploy_frontend; do
  [ -f "/root/.ssh/$k" ] || { echo "  MISSING /root/.ssh/$k - see deploy/README.md (deploy keys)"; exit 1; }
done
ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts
clone_or_pull() {
  local url="$1" dir="$2"
  if [ -d "$dir/.git" ]; then git -C "$dir" pull --ff-only
  else git clone "$url" "$dir"; fi
}
clone_or_pull "$BACKEND_REPO"  "$REPO_ROOT/Ayurveda-"
clone_or_pull "$FRONTEND_REPO" "$REPO_ROOT/ayurveda-frontend"

log "5/8  secrets check"
mkdir -p "$SECRETS_DIR"; chmod 700 "$SECRETS_DIR"
missing=0
for f in convex.env convex-cli.env frontend.env backend.env; do
  if [ ! -f "$SECRETS_DIR/$f" ]; then
    echo "  MISSING $SECRETS_DIR/$f   (template: deploy/env/$f.example)"
    missing=1
  else
    chmod 600 "$SECRETS_DIR/$f"
  fi
done
[ "$missing" -eq 0 ] || { echo; echo "Fill the files above, then re-run. Nothing was started."; exit 1; }

log "6/8  dependencies"
cd "$REPO_ROOT/ayurveda-frontend" && "$BUN" install --frozen-lockfile
cd "$REPO_ROOT/Ayurveda-/backend-python"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt

log "7/8  systemd units"
install -m 644 "$REPO_ROOT/Ayurveda-/deploy/systemd/"*.service /etc/systemd/system/
install -m 644 "$REPO_ROOT/Ayurveda-/deploy/systemd/"*.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable convex.service ayurveda-backend.service ayurveda-frontend.service convex-backup.timer

log "8/8  start Convex"
systemctl start convex.service

cat <<'NEXT'

Convex is up. The remaining steps are deliberate and manual, because each one
can destroy data if run at the wrong moment:

  1. Admin key, if this is a new deployment:
       cd /opt/ayurveda/Ayurveda-/deploy/compose
       docker compose exec backend ./generate_admin_key.sh
     Put it in /etc/ayurveda/convex-cli.env

  2. Auth keys, ONCE per deployment (regenerating logs everyone out):
       node /opt/ayurveda/Ayurveda-/scripts/generateKeys.mjs
       npx convex env set JWT_PRIVATE_KEY -- "$(cat /tmp/jwt_private_key)"
       npx convex env set JWKS -- "$(cat /tmp/jwks)"

  3. Deployment variables: SITE_URL, BACKEND_*, SMTP_*  (npx convex env set)

  4. Push functions, then import data - schema before rows:
       cd /opt/ayurveda/ayurveda-frontend/packages/backend
       npx convex deploy
       npx convex import --replace <backup.zip>

  5. Build the frontend AFTER frontend.env is final (NEXT_PUBLIC_* are baked in):
       cd /opt/ayurveda/ayurveda-frontend/apps/app && bun run build

  6. systemctl start ayurveda-backend ayurveda-frontend
     cloudflared service install <token>   (or copy the tunnel credentials)

NEXT
