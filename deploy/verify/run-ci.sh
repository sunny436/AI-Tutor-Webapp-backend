#!/usr/bin/env bash
#
# The three jobs of .github/workflows/ci.yml, command for command, for `bun run verify`
# (deploy/verify.mjs runs this inside the container of deploy/verify/). Each job starts from its
# own fresh copy of `git archive <commit>` (/in/src.tar), as each CI job starts from its own
# checkout, with that job's `env:` and working directories. One `@@STEP {json}` line per command;
# after a failed command the rest of that job is skipped (as in CI). The exit code is always 0:
# the caller decides from the step results.
#
# The jobs run at the same time, as on CI, each in its own subshell with its own log: one
# progress line per command meanwhile, then every job's log whole, job by job. The end-to-end
# tests start only once the other two jobs have finished: on CI every job has a machine of its
# own, and these timing-sensitive tests get a quiet one here too. Downloads are kept between runs
# in /cache (compose.yml); pip and Bun still check every package against the commit's lockfiles.
#
# deploy/tests/ci-parity.test.mjs fails if a job, a command, a working directory or an env value
# here differs from ci.yml. Change both together.
set -uo pipefail
BASE_PATH=$PATH
exec 3>&1 # progress lines; each job's own output goes to its log

job() { # <job name exactly as in ci.yml> <directory>
  JOB=$1 ROOT=/work/$2 FAILED=0
  trap 'touch "$ROOT.done"' EXIT
  rm -rf "$ROOT" && mkdir -p "$ROOT" && tar -xf /in/src.tar -C "$ROOT"
  export PATH=$BASE_PATH
  printf '@@JOB %s\n' "$JOB"
}

step() { # <working directory in the checkout> <command, exactly as in ci.yml>
  local dir=$1 command=$2 code start
  if [ "$FAILED" = 1 ]; then
    python3.12 -c 'import json,sys; print("@@STEP " + json.dumps({"job": sys.argv[1], "dir": sys.argv[2], "command": sys.argv[3], "exit": None, "skipped": True}))' "$JOB" "$dir" "$command"
    printf 'skip  %s: %s\n' "${JOB%% (*}" "$command" >&3
    return
  fi
  printf '\n@@RUN [%s] (%s) %s\n' "$JOB" "$dir" "$command"
  start=$(date +%s)
  (cd "$ROOT/$dir" && bash -eo pipefail -c "$command")
  code=$?
  python3.12 -c 'import json,sys; print("@@STEP " + json.dumps({"job": sys.argv[1], "dir": sys.argv[2], "command": sys.argv[3], "exit": int(sys.argv[4]), "seconds": int(sys.argv[5])}))' \
    "$JOB" "$dir" "$command" "$code" "$(($(date +%s) - start))"
  printf '%-5s %s: %s (%ss)\n' "$([ "$code" = 0 ] && echo ok || echo FAIL)" "${JOB%% (*}" "$command" "$(($(date +%s) - start))" >&3
  [ "$code" = 0 ] || FAILED=1
}

after() { # <job directory>...: wait until those jobs have finished
  local dir
  for dir in "$@"; do while [ ! -e "/work/$dir.done" ]; do sleep 2; done; done
}

printf '@@RUNNER %s\n' "$(python3.12 -c 'import json,platform,subprocess as s; v=lambda *c: s.run(c,capture_output=True,text=True).stdout.strip(); print(json.dumps({"os": platform.freedesktop_os_release().get("PRETTY_NAME"), "arch": platform.machine(), "python": platform.python_version(), "node": v("node","--version"), "bun": v("bun","--version")}))')"

# ------------------------------------------------------------------ backend
(
job "Backend (lint, contract, tests)" backend-job
export TEST_DATABASE_URL=postgresql+asyncpg://aichat:aichat@127.0.0.1:5432/aichat_test
export PIP_CACHE_DIR=/cache/pip-backend
# actions/setup-python (3.12) gives the job its own `python`; here a venv outside the checkout.
python3.12 -m venv /opt/ci-python && export PATH=/opt/ci-python/bin:$PATH
step backend "python -m pip install --require-hashes -r requirements.lock"
step backend "python -m pip install -r requirements-dev.txt"
step backend "python -m pip check"
step backend "ruff check ."
step backend "ruff format --check ."
step backend "python scripts/export_openapi.py --check"
step backend 'python -m pytest -o addopts="" -ra'
) > /work/backend-job.log 2>&1 &

# ------------------------------------------------------------------ frontend
(
job "Frontend (typecheck, lint, tests incl. contract, build)" frontend-job
export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
export BUN_INSTALL_CACHE_DIR=/cache/bun-frontend
step frontend "bun install --frozen-lockfile"
step frontend "bun run typecheck"
step frontend "bun run lint"
step frontend "bun run test"
step frontend "bun test ../deploy/tests"
step frontend "bun run build"
) > /work/frontend-job.log 2>&1 &

# ------------------------------------------------------------------ integration
(
job "Integration (end-to-end)" integration-job
export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
export PIP_CACHE_DIR=/cache/pip-integration BUN_INSTALL_CACHE_DIR=/cache/bun-integration PLAYWRIGHT_BROWSERS_PATH=/cache/ms-playwright
step backend "python -m venv .venv"
step backend ".venv/bin/python -m pip install --require-hashes -r requirements.lock"
step backend ".venv/bin/python -m alembic upgrade head"
step frontend "bun install --frozen-lockfile"
step frontend "cd apps/app && bunx playwright install --with-deps chromium webkit"
after backend-job frontend-job
step . "bun run test:e2e"
) > /work/integration-job.log 2>&1 &

wait
for dir in backend-job frontend-job integration-job; do printf '\n'; cat "/work/$dir.log"; done
exit 0
