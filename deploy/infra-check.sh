#!/usr/bin/env bash
#
# Verify INFRASTRUCTURE.md against the machine it describes.
#
#   bash deploy/infra-check.sh
#
# A document like that one rots quietly: something changes, nobody edits the
# file, and six months later it is confidently wrong. This turns its claims into
# assertions that either hold or do not.
#
# Run it on the VM. Exit code 0 = everything matches, 1 = drift found. Nothing
# here writes, restarts or repairs anything.
set -uo pipefail

REPO="/opt/ayurveda/Ayurveda-"
FRONTEND="/opt/ayurveda/ayurveda-frontend"
SECRETS="/etc/ayurveda"
DOC="$REPO/INFRASTRUCTURE.md"

pass=0; drift=0
ok()    { printf '  \033[32mOK\033[0m    %-34s %s\n' "$1" "${2:-}"; pass=$((pass+1)); }
bad()   { printf '  \033[31mDRIFT\033[0m %-34s %s\n' "$1" "${2:-}"; drift=$((drift+1)); }
note()  { printf '  \033[33m·\033[0m     %-34s %s\n' "$1" "${2:-}"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# --- 1. the machine -----------------------------------------------------------
head_ "machine"
[ "$(hostname)" = "askhat-linux-325-37" ] \
  && ok "hostname" "$(hostname)" \
  || bad "hostname" "$(hostname) — doc says askhat-linux-325-37"

ip -4 -o addr show scope global 2>/dev/null | grep -q "10.1.30.37" \
  && ok "address" "10.1.30.37" \
  || bad "address" "10.1.30.37 not found on any interface"

# Swap is not a nicety here: 3.8 GB cannot hold `next build` and a running
# backend at the same time without it.
sw=$(free -m | awk '/^Swap:/{print $2}')
[ "${sw:-0}" -ge 2000 ] && ok "swap" "${sw} MB" || bad "swap" "${sw} MB — doc says 4 GB"

freeg=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "${freeg:-0}" -ge 5 ] && ok "disk free" "${freeg} GB" || bad "disk free" "${freeg} GB — low"

# --- 2. services --------------------------------------------------------------
head_ "services (section 2)"
for u in docker convex ayurveda-backend ayurveda-frontend cloudflared; do
  en=$(systemctl is-enabled "$u" 2>/dev/null || echo missing)
  ac=$(systemctl is-active  "$u" 2>/dev/null || echo inactive)
  if [ "$en" = "enabled" ] && [ "$ac" = "active" ]; then
    ok "$u" "enabled + active"
  else
    # `enabled` without `active` is the failure mode that bit the backup timer:
    # enable only arranges a start at boot, it does not start anything now.
    bad "$u" "enabled=$en active=$ac"
  fi
done

# Memory caps exist so a Python spike cannot get Convex killed by the OOM
# reaper. If they are gone the doc is lying about a real safety property.
mh=$(systemctl show ayurveda-backend -p MemoryHigh --value 2>/dev/null)
[ -n "$mh" ] && [ "$mh" != "infinity" ] \
  && ok "backend MemoryHigh" "$mh" \
  || bad "backend MemoryHigh" "unset — doc says 2200M"

# --- 3. ports -----------------------------------------------------------------
head_ "ports (section 2)"
for p in 3000 4000 3210 3211; do
  ss -lntH 2>/dev/null | grep -qE ":$p\b" && ok "port $p" listening || bad "port $p" "nothing listening"
done
ss -lntH 2>/dev/null | grep -qE ":6791\b" \
  && ok "port 6791 (dashboard)" "listening, not tunnelled" \
  || note "port 6791 (dashboard)" "not listening"

# --- 4. tunnel ----------------------------------------------------------------
head_ "tunnel (section 3)"
CFG=/etc/cloudflared/config.yml
if [ -f "$CFG" ]; then
  for h in ayur.namahos.com ayur-api.namahos.com ayur-convex.namahos.com ayur-convex-http.namahos.com; do
    grep -q "hostname: $h" "$CFG" && ok "ingress $h" || bad "ingress $h" "missing from $CFG"
  done
  # The catch-all must be last, or a later rule is unreachable.
  if [ "$(grep -n 'http_status:404' "$CFG" | cut -d: -f1)" -gt "$(grep -n 'hostname:' "$CFG" | tail -1 | cut -d: -f1)" ]; then
    ok "catch-all is last"
  else
    bad "catch-all is last" "a hostname appears after http_status:404"
  fi
else
  bad "tunnel config" "$CFG missing"
fi

# --- 5. public reachability ---------------------------------------------------
head_ "public endpoints (section 3)"
probe() {
  # The JWKS fetch sends this UA on purpose: Cloudflare answers the default
  # Python-urllib agent with 403, which is what broke every login once.
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 25 -A 'ayurveda-infra-check/1.0' "$2" 2>/dev/null)
  [ "$c" = "200" ] && ok "$1" "200" || bad "$1" "HTTP $c"
}
probe "app /en/login"  https://ayur.namahos.com/en/login
probe "api /health"    https://ayur-api.namahos.com/health
probe "convex version" https://ayur-convex.namahos.com/version
probe "convex jwks"    https://ayur-convex-http.namahos.com/.well-known/jwks.json

# --- 6. data + backups --------------------------------------------------------
head_ "data and backups (section 6)"
docker volume ls -q 2>/dev/null | grep -q 'compose_data' \
  && ok "convex volume" "compose_data" \
  || bad "convex volume" "compose_data not found"

systemctl is-active convex-backup.timer >/dev/null 2>&1 \
  && ok "backup timer" "$(systemctl list-timers convex-backup --no-pager 2>/dev/null | sed -n 2p | awk '{print $1,$2,$3}')" \
  || bad "backup timer" "not active — enable alone does not start a timer"

n=$(ls "$REPO"/../../var/backups/convex/*.zip /var/backups/convex/*.zip 2>/dev/null | wc -l)
if [ "$n" -gt 0 ]; then
  newest=$(ls -t /var/backups/convex/*.zip 2>/dev/null | head -1)
  age=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 86400 ))
  [ "$age" -le 2 ] && ok "backup freshness" "${age}d old, ${n} archives" \
                   || bad "backup freshness" "newest is ${age} days old"
else
  bad "backups" "no archives in /var/backups/convex"
fi

# A backup on the same disk as the database does not survive the failure it
# exists for. Documented as known gap #1; this keeps it visible.
grep -qE '^[[:space:]]*rclone copy' "$REPO/deploy/backup.sh" 2>/dev/null \
  && ok "off-box backup copy" "configured" \
  || bad "off-box backup copy" "still commented out (known gap #1)"

# The knowledge index is a gitignored build artifact. Missing, the backend
# starts fine and answers every consultation ungrounded.
[ -d "$REPO/backend-python/data/vector_store" ] && [ -n "$(ls -A "$REPO/backend-python/data/vector_store" 2>/dev/null)" ] \
  && ok "knowledge index" "$(du -sh "$REPO/backend-python/data/vector_store" 2>/dev/null | cut -f1)" \
  || bad "knowledge index" "empty — backend will answer ungrounded"

# --- 7. secrets ---------------------------------------------------------------
head_ "environment (section 5)"
for f in convex.env convex-cli.env frontend.env backend.env; do
  if [ -f "$SECRETS/$f" ]; then
    m=$(stat -c %a "$SECRETS/$f")
    [ "$m" = "600" ] && ok "$f" "present, mode $m" || bad "$f" "mode $m — should be 600"
  else
    bad "$f" "missing from $SECRETS"
  fi
done

# Names only. Values are never read, printed or logged by this script.
need() {
  file="$SECRETS/$1"; shift
  for v in "$@"; do
    grep -qE "^${v}=." "$file" 2>/dev/null || bad "$(basename "$file"):$v" "unset or empty"
  done
}
need convex.env      CONVEX_CLOUD_ORIGIN CONVEX_SITE_ORIGIN INSTANCE_NAME INSTANCE_SECRET
need convex-cli.env  CONVEX_SELF_HOSTED_URL CONVEX_SELF_HOSTED_ADMIN_KEY
need frontend.env    NEXT_PUBLIC_CONVEX_URL NEXT_PUBLIC_SITE_URL NEXT_PUBLIC_AI_BACKEND_URL
need backend.env     CONVEX_SITE_URL CONVEX_AUDIENCE SERVICE_KEY WEBHOOK_SECRET
ok "required var names" "checked (names only, no values read)"

# config.py defaults this to localhost. If backend.env omits it, JWKS resolves
# to loopback and every login 401s with "your session expired".
grep -qE '^CONVEX_SITE_URL=https://' "$SECRETS/backend.env" 2>/dev/null \
  && ok "backend CONVEX_SITE_URL" "https, not the localhost default" \
  || bad "backend CONVEX_SITE_URL" "not https — logins will fail silently"

# --- 8. code provenance -------------------------------------------------------
head_ "code and deployment (section 4)"
for d in "$REPO" "$FRONTEND"; do
  n=$(basename "$d")
  if [ -d "$d/.git" ]; then
    # Matches the SSH Host ALIASES too (git@github-backend:...). Grepping for a
    # literal github.com reported every correct deploy-key remote as drift,
    # which is how this check first earned its keep - on itself.
    url=$(git -C "$d" remote get-url origin 2>/dev/null)
    case "$url" in
      *github.com*|git@github-backend:*|git@github-frontend:*)
        ok "$n origin" "$(git -C "$d" log --oneline -1 | cut -c1-46)" ;;
      *) bad "$n origin" "unexpected remote: ${url:-none}" ;;
    esac
    behind=$(git -C "$d" fetch -q 2>/dev/null; git -C "$d" rev-list --count HEAD..@{u} 2>/dev/null || echo '?')
    [ "$behind" = "0" ] && ok "$n up to date" || note "$n" "$behind commits behind origin"
  else
    bad "$n" "not a git checkout"
  fi
done

# --- 9. drift the doc already admits ------------------------------------------
head_ "known gaps (section 8)"
img=$(docker inspect compose-backend-1 --format '{{.Config.Image}}' 2>/dev/null)
case "$img" in
  *:latest) bad "convex image pinned" "$img (known gap #4)" ;;
  "")       bad "convex image" "container not found" ;;
  *)        ok  "convex image pinned" "$img" ;;
esac

[ -f "$REPO/self-hosted/docker-compose.yml" ] \
  && bad "single compose file" "self-hosted/ duplicate still present (known gap #5)" \
  || ok  "single compose file" "deploy/compose only"

# --- summary ------------------------------------------------------------------
printf '\n\033[1msummary\033[0m\n'
printf '  %d checks passed, %d drifted\n' "$pass" "$drift"
if [ "$drift" -eq 0 ]; then
  printf '  \033[32mINFRASTRUCTURE.md matches this machine.\033[0m\n'
  printf '  Update the "Last verified" date at the top of %s\n\n' "$DOC"
  exit 0
fi
printf '  \033[31mFix the machine, or fix the document — do not leave them disagreeing.\033[0m\n\n'
exit 1
