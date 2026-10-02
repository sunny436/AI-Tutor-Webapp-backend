#!/usr/bin/env bash
#
# What production runs, and whether it is healthy. Read-only. From a workstation:
# `bun run status` (pipes lib.sh + this file over ssh); on the host:
#   bash /opt/aichat/app/deploy/server/status.sh
#
# Checks the production checkout /opt/aichat/app against production Git, that the backend and
# the frontend run the checkout's code (content keys, lib.sh), both units and their health, and
# web.env's API_BASE_URL. The public URL is shown, never required. Exits 1 on any failure; its
# last line ("@@STATUS ...") is read by deploy/status.sh.
set -uo pipefail
declare -F tree_key > /dev/null || . "$(dirname "$(readlink -f "$0")")/lib.sh"
fail=0
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }
ok() { printf '  ok    %s\n' "$*"; }
info() { printf '        %s\n' "$*"; }

echo "production"
if [ ! -d "$APP/.git" ]; then
  bad "no production checkout at $APP (the host still runs the old release layout: bun run deploy)"
  exit 1
fi
HEAD=$(git -C "$APP" rev-parse HEAD)
BARE=$(git --git-dir="$APP_GIT" rev-parse -q --verify refs/heads/main 2> /dev/null)
ok "checkout $APP at $HEAD ($(git -C "$APP" log -1 --format=%s))"
[ "$BARE" = "$HEAD" ] && ok "production Git main == the checkout" || bad "production Git main is ${BARE:-missing}, the checkout is $HEAD: the last deploy did not finish"
[ -z "$(git -C "$APP" status --porcelain --untracked-files=no)" ] && ok "no local edits in the checkout" || bad "the checkout has local edits (git -C $APP status): only deploys change it"

api=$(reported_release "http://127.0.0.1:$API_PORT/health")
web=$(reported_release "http://127.0.0.1:$WEB_PORT/api/health")
K_BACK=$(key_backend) K_FRONT=$(key_frontend)
bcur=no fcur=no
if [ "$(running_key backend)" = "$K_BACK" ]; then bcur=yes; ok "backend: aichat-api runs the checkout's backend code (deployed with $(running_commit backend); reports ${api:-nothing})"; else bad "backend: aichat-api runs older backend code ($(running_commit backend)): deploy again"; fi
if [ "$(running_key frontend)" = "$K_FRONT" ]; then fcur=yes; ok "frontend: aichat-web serves the checkout's frontend build (built from $(running_commit frontend); reports ${web:-nothing})"; else bad "frontend: aichat-web serves an older build ($(running_commit frontend)): deploy again"; fi

echo "services"
for unit in aichat-api aichat-web; do
  systemctl is-active --quiet "$unit" && ok "$unit active" || bad "$unit is not active (journalctl -u $unit)"
  case "$(systemctl show -p WorkingDirectory --value "$unit" 2> /dev/null)" in "$APP"/*) ;; *) bad "$unit does not run from $APP" ;; esac
done
curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$API_PORT/ready" && ok "API /health and /ready (database reachable)" || bad "API /ready fails"
curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$WEB_PORT/login" && ok "web /login" || bad "web /login fails"
grep -qE '^API_BASE_URL=http://127\.0\.0\.1:4100/?$' "$SECRETS/web.env" 2> /dev/null && ok "web.env API_BASE_URL -> the API on :4100" || bad "web.env API_BASE_URL is not http://127.0.0.1:4100"
missing=""
for name in AUTH_DATABASE_URL BETTER_AUTH_SECRET AUTH_INTERNAL_TOKEN; do grep -qE "^$name=.+" "$SECRETS/web.env" 2> /dev/null || missing="$missing $name"; done
[ -z "$missing" ] && ok "web.env has the sign-in settings (values not shown)" || bad "web.env is missing:$missing"
[ -n "$(env_value AUTH_INTERNAL_TOKEN api.env)" ] && [ "$(env_value AUTH_INTERNAL_TOKEN api.env)" = "$(env_value AUTH_INTERNAL_TOKEN web.env)" ] \
  && ok "AUTH_INTERNAL_TOKEN set and the same in api.env and web.env" || bad "AUTH_INTERNAL_TOKEN missing or different in api.env and web.env"
web_auth_ok "$WEB_PORT" && ok "web sign-in database reachable (/api/health)" || bad "web reports its sign-in database unavailable (/api/health)"
grep -qE '^GOOGLE_CLIENT_ID=.+' "$SECRETS/web.env" 2> /dev/null && info "Google sign-in: configured" || info "Google sign-in: not configured (the button is hidden)"
grep -qE '^TURNSTILE_SECRET_KEY=.+' "$SECRETS/web.env" 2> /dev/null && info "CAPTCHA (Turnstile): configured" || info "CAPTCHA (Turnstile): not configured (adaptive CAPTCHA off)"
public=$(sed -n 's/^NEXT_PUBLIC_SITE_URL=//p' "$SECRETS/web.env" 2> /dev/null)
if [ -n "$public" ]; then info "public $public/login -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$public/login" || true) (information: Cloudflare/DNS)"; fi
jobs_timer=$(systemctl is-enabled aichat-jobs.timer 2> /dev/null); info "jobs worker: aichat-jobs.timer ${jobs_timer:-not installed}"
files=$(curl -fsS --max-time 5 "http://127.0.0.1:$API_PORT/health" 2> /dev/null | grep -o '"files":"[a-z]*"' | cut -d'"' -f4)
info "files (File Library): ${files:-unknown}; extractor units running: $(systemctl list-units --no-legend 'aichat-extract-*' 2> /dev/null | wc -l)"
# No stale or old release serving traffic (the owner's production rule): the legacy Ayurveda API
# (:4000) and its Convex (3210, 3211, 6791) must not listen.
stale=$(ss -ltnH 2> /dev/null | awk '{print $4}' | grep -cE ':(4000|3210|3211|6791)$' || true)
[ "${stale:-0}" -eq 0 ] && ok "no stale release listening (4000/3210/3211/6791 free)" || bad "a stale release is listening on a legacy port (4000/3210/3211/6791)"
for legacy in /opt/aichat/backend /opt/aichat/frontend /opt/aichat/releases; do
  [ -e "$legacy" ] && info "note: $legacy is from an older layout (not used; remove after approval)"
done

if [ -f "$HISTORY" ]; then echo "last deploys"; tail -3 "$HISTORY" | sed 's/^/        /'; fi
printf '@@STATUS checkout=%s backend=%s frontend=%s backend_current=%s frontend_current=%s\n' \
  "$HEAD" "$(running_commit backend)" "$(running_commit frontend)" "$bcur" "$fcur"
exit "$fail"
