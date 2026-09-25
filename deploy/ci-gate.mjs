#!/usr/bin/env bun
/**
 * The CI gate of `bun run deploy`: a commit may reach production only if GitHub reports every
 * REQUIRED CI job as completed with success for that exact commit.
 *
 *   bun deploy/ci-gate.mjs <commit>      prints the evidence (JSON) and exits 0, or explains and exits 1
 *
 * Fails closed: a missing job, a job still running, any conclusion other than "success", an
 * unreachable GitHub or a missing token all refuse the deploy. Branch protection is not
 * available on this repository's plan, so this gate is what enforces "CI passed". The token
 * comes from git's credential helper and is never printed.
 */
import { spawnSync } from "node:child_process";

export const REPOSITORY = "sunny436/AI-Tutor-Webapp-backend";
// The `name:` of each job in .github/workflows/ci.yml. Removing a job from CI does not weaken
// the gate: a required job that did not run is a failure.
export const REQUIRED_JOBS = [
  "Backend (lint, contract, tests)",
  "Frontend (typecheck, lint, tests incl. contract, build)",
  "Integration (end-to-end)",
];

/** Decide from GitHub's check runs for one commit. Latest run of each name wins (re-runs). */
export function evaluate(checkRuns, required = REQUIRED_JOBS) {
  const latest = new Map();
  for (const run of checkRuns) {
    const seen = latest.get(run.name);
    if (!seen || run.id > seen.id) latest.set(run.name, run);
  }
  const problems = [];
  const jobs = [];
  for (const name of required) {
    const run = latest.get(name);
    if (!run) {
      problems.push(`${name}: did not run`);
      continue;
    }
    if (run.status !== "completed") problems.push(`${name}: still ${run.status}`);
    else if (run.conclusion !== "success") problems.push(`${name}: ${run.conclusion}`);
    jobs.push({ name, id: run.id, conclusion: run.conclusion ?? run.status, url: run.html_url });
  }
  return { ok: problems.length === 0, problems, jobs };
}

function githubToken() {
  const result = spawnSync("git", ["credential", "fill"], {
    input: "protocol=https\nhost=github.com\n\n",
    encoding: "utf8",
    env: { ...process.env, GIT_TERMINAL_PROMPT: "0", GCM_INTERACTIVE: "Never" },
    timeout: 30_000,
  });
  const line = (result.stdout ?? "").split("\n").find((l) => l.startsWith("password="));
  return line ? line.slice("password=".length).trim() : "";
}

async function main(sha) {
  if (!/^[0-9a-f]{40}$/.test(sha ?? "")) throw new Error("usage: bun deploy/ci-gate.mjs <40-character commit>");
  const token = githubToken();
  if (!token) throw new Error("no GitHub credential available (git credential fill); cannot verify CI");
  const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/commits/${sha}/check-runs?per_page=100`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`GitHub answered ${response.status}; cannot verify CI`);
  const { check_runs: checkRuns = [] } = await response.json();
  const verdict = evaluate(checkRuns);
  if (!verdict.ok) {
    console.error(`CI has not passed for ${sha}:`);
    for (const problem of verdict.problems) console.error(`  - ${problem}`);
    process.exit(1);
  }
  console.log(JSON.stringify({ sha, checked_at: new Date().toISOString(), repository: REPOSITORY, jobs: verdict.jobs }));
}

if (import.meta.main) {
  main(process.argv[2]).catch((error) => {
    console.error(`CI gate: ${error.message}`);
    process.exit(1);
  });
}
