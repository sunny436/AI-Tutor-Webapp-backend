#!/usr/bin/env bun
/**
 * GitHub CI's verdict on one commit: every REQUIRED job completed with success, or not.
 *
 *   bun deploy/ci-gate.mjs <commit>            prints the evidence (JSON) and exits 0, or explains and exits 1
 *   bun deploy/ci-gate.mjs --report <commit>   one line for `bun run status`; always exits 0
 *
 * Advisory only: `bun run deploy` never waits for CI (docs/deployment.md). CI still runs on every
 * push, and `bun run status` shows its verdict on the production checkout. REQUIRED_JOBS is also
 * the list of jobs the optional `bun run verify` runs (deploy/tests/ci-parity.test.mjs).
 * The token comes from git's credential helper and is never printed.
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

/** One informational line; never fails. */
async function report(sha) {
  try {
    const token = githubToken();
    if (!token) return "unavailable (no GitHub credential)";
    const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/commits/${sha}/check-runs?per_page=100`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
      signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) return `unavailable (GitHub answered ${response.status})`;
    const { check_runs: checkRuns = [] } = await response.json();
    const verdict = evaluate(checkRuns);
    if (verdict.ok) return `success (${verdict.jobs.map((job) => job.name.split(" (")[0]).join(", ")})`;
    // A job GitHub refused to start (billing, spending limit) also concludes "failure": say so.
    const notStarted = [];
    for (const job of verdict.jobs.filter((candidate) => candidate.conclusion === "failure")) {
      const annotations = await fetch(`https://api.github.com/repos/${REPOSITORY}/check-runs/${job.id}/annotations`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
        signal: AbortSignal.timeout(20_000),
      }).then((reply) => (reply.ok ? reply.json() : []));
      const refusal = annotations.find((annotation) => /job was not started/i.test(annotation.message ?? ""));
      if (refusal) notStarted.push(job.name);
    }
    if (notStarted.length === verdict.jobs.length && notStarted.length > 0) return "not run (GitHub did not start the jobs: Actions billing or spending limit)";
    const failed = verdict.problems.filter((problem) => /: (failure|cancelled|timed_out|action_required)$/.test(problem) && !notStarted.some((name) => problem.startsWith(name)));
    if (failed.length) return `FAILURE: ${failed.join("; ")}`;
    return `not passed: ${verdict.problems.join("; ")}`;
  } catch (error) {
    return `unavailable (${error.message})`;
  }
}

if (import.meta.main) {
  if (process.argv[2] === "--report") {
    report(process.argv[3] ?? "").then((line) => console.log(line));
  } else {
    main(process.argv[2]).catch((error) => {
      console.error(`CI gate: ${error.message}`);
      process.exit(1);
    });
  }
}
