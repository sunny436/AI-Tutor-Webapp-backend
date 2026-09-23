#!/usr/bin/env bash
#
# Compare the host against the target described in INFRASTRUCTURE.md. Read-only.
#   bash deploy/infra-check.sh
set -uo pipefail
fail=0
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }

echo "units"
for u in aichat-postgres.service aichat-api.service aichat-pg-backup.timer; do
  systemctl is-active --quiet "$u" && ok "$u active" || bad "$u not active"
done

echo "network exposure (loopback only)"
for port in 4000 5432; do
  if ss -ltnH "( sport = :$port )" | awk '{print $4}' | grep -qvE '^(127\.0\.0\.1|\[::1\]):'; then
    bad "port $port listens beyond loopback"
  else
    ok "port $port bound to loopback"
  fi
done

echo "health"
curl -fsS http://127.0.0.1:4000/health >/dev/null && ok "api /health" || bad "api /health"
curl -fsS http://127.0.0.1:4000/ready  >/dev/null && ok "api /ready (database reachable)" || bad "api /ready"
curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/docs | grep -q 404 && ok "api docs hidden" || bad "api docs exposed"

echo "backups"
latest=$(ls -1t /var/backups/aichat/aichat-*.dump 2>/dev/null | head -1)
if [ -n "$latest" ] && [ "$(find "$latest" -mtime -2 | wc -l)" -eq 1 ]; then ok "recent backup $latest"; else bad "no backup in the last 2 days"; fi

exit $fail
