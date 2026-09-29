#!/usr/bin/env bash
#
# Compare the host against INFRASTRUCTURE.md. Read-only.
#   bash /opt/aichat/app/deploy/infra-check.sh
#
# First what production runs (deploy/server/status.sh: the checkout, the code each part runs,
# health), then the host.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/server/lib.sh"
fail=0
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }
API="http://127.0.0.1:$API_PORT"

bash "$(dirname "$(readlink -f "$0")")/server/status.sh" || fail=1

echo
echo "services"
for u in aichat-postgres.service aichat-api.service aichat-web.service aichat-pg-backup.timer; do
  systemctl is-active --quiet "$u" && ok "$u active" || bad "$u not active"
done

echo "network exposure (loopback only)"
for port in "$WEB_PORT" "$API_PORT" 5432; do
  if ss -ltnH "( sport = :$port )" | awk '{print $4}' | grep -vE '^(127\.0\.0\.1|\[::1\]):' >/dev/null; then
    bad "port $port listens beyond loopback"
  else
    ok "port $port bound to loopback"
  fi
done

echo "health"
curl -fsS "$API/ready" >/dev/null && ok "api /ready (database reachable)" || bad "api /ready"
curl -sS -o /dev/null -w '%{http_code}' "$API/docs" | grep -q 404 && ok "api docs hidden" || bad "api docs exposed"
curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT/login" && ok "web app serves /login" || bad "web app not answering on :$WEB_PORT"
check_chain "$WEB_PORT" aichat-api >/dev/null && ok "web -> API -> database" || bad "web app cannot reach the API"

echo "database"
[ -f "$SHARED/postgres/docker-compose.yml" ] && ok "compose file in $SHARED/postgres" || bad "missing $SHARED/postgres/docker-compose.yml"
latest=$(ls -1t /var/backups/aichat/aichat-*.dump 2>/dev/null | head -1)
if [ -n "$latest" ] && [ "$(find "$latest" -mtime -2 | wc -l)" -eq 1 ]; then ok "recent backup $latest"; else bad "no backup in the last 2 days"; fi
free_gb=$(( $(df --output=avail -B1 / | tail -1 | tr -dc '0-9') / 1000000000 ))
[ "$free_gb" -ge 5 ] && ok "disk: ${free_gb} GB free (uploads stop under 5 GB)" || bad "disk: only ${free_gb} GB free: file uploads are refused and backups may fail"

echo "files (app/files)"
langs=$(tesseract --list-langs 2>/dev/null | tail -n +2)
if grep -qx eng <<<"$langs" && grep -qx hin <<<"$langs"; then ok "tesseract with eng and hin (OCR)"; else bad "tesseract with eng and hin is missing (apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin)"; fi
keep=$(sed -n 's/^KEEP_DAYS=//p' /etc/aichat/postgres.env 2>/dev/null)
[ "${keep:-7}" -le 7 ] 2>/dev/null && ok "backups kept ${keep:-7} days" || bad "KEEP_DAYS=${keep} in postgres.env: keep it at 7 (dumps share the database's disk)"
files=$(curl -fsS --max-time 5 "$API/health" 2>/dev/null | grep -o '"files":"[a-z]*"' | cut -d'"' -f4)
[ "$files" = available ] && ok "files available (sandbox self-test passed)" || bad "files ${files:-unknown}: see journalctl -u aichat-api (files self-test)"

exit $fail
