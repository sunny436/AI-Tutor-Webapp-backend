#!/usr/bin/env bash
#
# Compare the host against the target described in INFRASTRUCTURE.md. Read-only.
#   bash deploy/infra-check.sh
set -uo pipefail
fail=0
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }
API="http://127.0.0.1:4100"

echo "units"
for u in aichat-postgres.service aichat-api.service aichat-pg-backup.timer; do
  systemctl is-active --quiet "$u" && ok "$u active" || bad "$u not active"
done
# The web unit runs only after the switch-over (docs/production-migration.md).
web_enabled=0
systemctl is-enabled --quiet aichat-web.service 2>/dev/null && web_enabled=1
if [ "$web_enabled" -eq 1 ]; then
  systemctl is-active --quiet aichat-web.service && ok "aichat-web.service active" || bad "aichat-web.service not active"
else
  ok "aichat-web.service not enabled yet (before the switch-over)"
fi

echo "network exposure (loopback only)"
ports="4100 5432"
[ "$web_enabled" -eq 1 ] && ports="$ports 3000"
for port in $ports; do
  if ss -ltnH "( sport = :$port )" | awk '{print $4}' | grep -qvE '^(127\.0\.0\.1|\[::1\]):'; then
    bad "port $port listens beyond loopback"
  else
    ok "port $port bound to loopback"
  fi
done

echo "health"
curl -fsS "$API/health" >/dev/null && ok "api /health" || bad "api /health"
curl -fsS "$API/ready"  >/dev/null && ok "api /ready (database reachable)" || bad "api /ready"
curl -fsS -o /dev/null -w '%{http_code}' "$API/docs" | grep -q 404 && ok "api docs hidden" || bad "api docs exposed"
if [ "$web_enabled" -eq 1 ]; then
  curl -fsS -o /dev/null http://127.0.0.1:3000/ && ok "web app answers on :3000" || bad "web app not answering on :3000"
fi

echo "backups"
latest=$(ls -1t /var/backups/aichat/aichat-*.dump 2>/dev/null | head -1)
if [ -n "$latest" ] && [ "$(find "$latest" -mtime -2 | wc -l)" -eq 1 ]; then ok "recent backup $latest"; else bad "no backup in the last 2 days"; fi

exit $fail
