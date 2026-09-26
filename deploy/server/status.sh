#!/usr/bin/env bash
#
# Which release is running, and proof that the web app and the API run the SAME one.
# Read-only. From a workstation: `bun run status` (pipes this file over ssh), or on the host:
#   bash /opt/aichat/current/deploy/server/status.sh
#
# Checks: /opt/aichat/current, the release each app reports (/health, /api/health), the
# release every aichat-api / aichat-web process runs from, that both units start from
# /opt/aichat/current, that the release's files are exactly its commit, and API_BASE_URL.
# Exits 1 unless everything agrees: "INVARIANT OK" means
#   FRONTEND_RUNNING_SHA == BACKEND_RUNNING_SHA == /opt/aichat/current.
set -uo pipefail

RELEASES=/opt/aichat/releases
CURRENT=/opt/aichat/current
fail=0
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }
ok() { printf '  ok    %s\n' "$*"; }
info() { printf '        %s\n' "$*"; }

release_of() {
  local path
  path=$(readlink -f "$1" 2>/dev/null) || return 0
  case "$path" in "$RELEASES"/*) path=${path#"$RELEASES"/}; printf '%s' "${path%%/*}" ;; esac
}
reported() {
  curl -fsS --max-time 5 "$1" 2>/dev/null \
    | python3.12 -c 'import json,sys; print(json.load(sys.stdin).get("release", ""))' 2>/dev/null
}
# The releases all processes of a unit run from (sorted, unique; "outside" for non-release dirs).
unit_releases() {
  local cgroup pid
  cgroup=$(systemctl show -p ControlGroup --value "$1" 2>/dev/null)
  [ -n "$cgroup" ] && [ -r "/sys/fs/cgroup$cgroup/cgroup.procs" ] || return 0
  while read -r pid; do
    [ -n "$pid" ] && { r=$(release_of "/proc/$pid/cwd"); printf '%s\n' "${r:-outside}"; }
  done < "/sys/fs/cgroup$cgroup/cgroup.procs" | sort -u
}
# The Node binaries the web app's processes run on (full path: it names the version).
runtime_of_web() {
  local cgroup pid exe
  cgroup=$(systemctl show -p ControlGroup --value aichat-web 2>/dev/null)
  [ -n "$cgroup" ] && [ -r "/sys/fs/cgroup$cgroup/cgroup.procs" ] || return 0
  while read -r pid; do
    exe=$(readlink "/proc/$pid/exe" 2>/dev/null) || continue
    case "$exe" in */node) printf '%s\n' "$exe" ;; esac
  done < "/sys/fs/cgroup$cgroup/cgroup.procs" | sort -u | tr '\n' ' '
}

echo "release"
pointer=$(release_of "$CURRENT")
if [ -n "$pointer" ]; then ok "/opt/aichat/current -> $pointer"; else bad "/opt/aichat/current does not point at a release (old layout?)"; fi
api=$(reported "http://127.0.0.1:4100/health")
web=$(reported "http://127.0.0.1:3000/api/health")
api_procs=$(unit_releases aichat-api | tr '\n' ' ')
web_procs=$(unit_releases aichat-web | tr '\n' ' ')
info "backend  (aichat-api) reports release=${api:-none}   processes run: ${api_procs:-none}"
info "frontend (aichat-web) reports release=${web:-none}   processes run: ${web_procs:-none}   runtime: $(runtime_of_web)"
[ "${api_procs% }" = "$pointer" ] && [ "${web_procs% }" = "$pointer" ] && [ -n "$pointer" ] \
  && ok "every aichat-api and aichat-web process runs $pointer" || bad "processes do not all run the pointer's release"
[ "$api" = "$pointer" ] && [ "$web" = "$pointer" ] && [ -n "$pointer" ] \
  && ok "frontend release == backend release == $pointer" || bad "reported releases differ (frontend=${web:-none}, backend=${api:-none}, pointer=${pointer:-none})"
if [ -n "$pointer" ] && [ -f "$RELEASES/$pointer/.node-version" ]; then
  want_node="/opt/aichat/runtime/node-v$(tr -d '[:space:]' < "$RELEASES/$pointer/.node-version")-linux-x64/bin/node"
  [ "$(runtime_of_web)" = "$want_node " ] && ok "web runs the release's pinned Node ($want_node)" \
    || bad "web does not run the release's pinned Node (expected $want_node, found: $(runtime_of_web))"
fi

echo "integrity"
if [ -n "$pointer" ] && [ -f "$RELEASES/$pointer/MANIFEST" ]; then
  if out=$(python3.12 "$RELEASES/$pointer/deploy/server/verify-release.py" "$RELEASES/$pointer" 2>&1); then ok "${out#"${out%%[![:space:]]*}"}"; else bad "release files differ from commit $pointer"; printf '%s\n' "$out" | sed 's/^/        /' | head -8; fi
else
  bad "no MANIFEST to verify the live release against its commit"
fi
[ -f "$RELEASES/$pointer/CI.json" ] && info "CI: $(python3.12 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("rehearsal (no CI)" if d.get("rehearsal") else ", ".join(j["name"].split(" (")[0] + " " + j["conclusion"] for j in d["jobs"]))' "$RELEASES/$pointer/CI.json" 2>/dev/null)"

echo "units"
for unit in aichat-api aichat-web; do
  start=$(systemctl show -p ExecStart --value "$unit" 2>/dev/null)
  dir=$(systemctl show -p WorkingDirectory --value "$unit" 2>/dev/null)
  case "$start $dir" in *"/opt/aichat/current"*) ok "$unit starts from /opt/aichat/current" ;; *) bad "$unit does NOT start from /opt/aichat/current ($dir)" ;; esac
done
if grep -qE '^API_BASE_URL=http://127\.0\.0\.1:4100/?$' /etc/aichat/web.env 2>/dev/null; then ok "web.env API_BASE_URL -> the API on :4100"; else bad "web.env API_BASE_URL is not http://127.0.0.1:4100"; fi
# The jobs worker is not part of the invariant: it runs from `current` whenever it runs.
jobs_timer=$(systemctl is-enabled aichat-jobs.timer 2>/dev/null); [ -n "$jobs_timer" ] || jobs_timer="not installed"
jobs_last=$(systemctl show -p ExecMainExitTimestamp --value aichat-jobs.service 2>/dev/null)
info "jobs worker: aichat-jobs.timer ${jobs_timer}; last run ${jobs_last:-never} ($(systemctl show -p Result --value aichat-jobs.service 2>/dev/null))"
for legacy in /opt/aichat/backend /opt/aichat/frontend; do
  [ -e "$legacy" ] && info "note: legacy checkout $legacy still exists (not used; remove after approval)"
done

if [ -f "$RELEASES/HISTORY" ]; then echo "last events"; tail -3 "$RELEASES/HISTORY" | sed 's/^/        /'; fi
echo
if [ "$fail" = 0 ]; then echo "INVARIANT OK: frontend and backend both run release $pointer"; else echo "INVARIANT FAIL"; fi
exit "$fail"
