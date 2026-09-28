#!/usr/bin/env bun
/**
 * The verification gate of `bun run deploy`: a commit may reach production only if
 * `bun run verify` passed on exactly that commit (its SHA and its tree) on this machine.
 *
 *   bun deploy/local-gate.mjs <commit>    prints the release evidence (JSON) and exits 0,
 *                                          or explains and exits 1
 *
 * The evidence is `.deploy/verified/<commit>.json` and its log `.deploy/verified/<commit>.log`,
 * written by deploy/verify.mjs after running the three CI jobs' commands in a Linux container on
 * `git archive <commit>`. Fails closed: missing or unreadable evidence, another commit or tree,
 * a failed or missing job, a log that is not the one the evidence names, or rehearsal evidence
 * outside rehearsal mode all refuse the deploy.
 *
 * This guards against accidents (a forgotten test, an edited commit), not against the operator:
 * whoever can run the deploy can also write this file (docs/deployment.md, accepted limitations).
 */
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

import { REQUIRED_JOBS } from "./ci-gate.mjs";

export const EVIDENCE_DIR = ".deploy/verified";
export const EVIDENCE_VERSION = 1;

const isSha = (value) => typeof value === "string" && /^[0-9a-f]{40}$/.test(value);

/**
 * Decide whether `evidence` allows deploying `sha` (whose tree is `tree`). `logSha256` is the
 * hash of the log file next to the evidence; `rehearsal` is true only in rehearsal mode.
 */
export function evaluate(evidence, { sha, tree, logSha256, rehearsal = false }) {
  const problems = [];
  if (!evidence || typeof evidence !== "object") return { ok: false, problems: ["no verification evidence"] };
  if (evidence.version !== EVIDENCE_VERSION) problems.push(`unknown evidence version ${evidence.version}`);
  if (!isSha(sha) || evidence.sha !== sha) problems.push(`verified ${evidence.sha ?? "nothing"}, not ${sha}`);
  if (!isSha(tree) || evidence.tree !== tree) problems.push(`verified tree ${evidence.tree ?? "none"}, but ${sha} has tree ${tree}`);
  if (evidence.rehearsal === true && !rehearsal) problems.push("rehearsal evidence cannot release to a real host");
  if (evidence.result !== "success") problems.push(`verification result: ${evidence.result ?? "none"}`);
  if (evidence.rehearsal !== true && (!logSha256 || evidence.log_sha256 !== logSha256)) {
    problems.push("the verification log is missing or is not the one the evidence names");
  }
  const jobs = Array.isArray(evidence.jobs) ? evidence.jobs : [];
  for (const name of REQUIRED_JOBS) {
    const job = jobs.find((candidate) => candidate?.name === name);
    if (!job) {
      problems.push(`${name}: did not run`);
      continue;
    }
    if (job.conclusion !== "success") problems.push(`${name}: ${job.conclusion}`);
    if (evidence.rehearsal !== true) {
      const steps = Array.isArray(job.steps) ? job.steps : [];
      if (steps.length === 0) problems.push(`${name}: no steps recorded`);
      for (const step of steps) if (step?.exit !== 0) problems.push(`${name}: "${step?.command}" exited ${step?.exit}`);
    }
  }
  return { ok: problems.length === 0, problems };
}

function git(...args) {
  const result = spawnSync("git", args, { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function main(sha) {
  if (!isSha(sha)) throw new Error("usage: bun deploy/local-gate.mjs <40-character commit>");
  const file = `${EVIDENCE_DIR}/${sha}.json`;
  const log = `${EVIDENCE_DIR}/${sha}.log`;
  if (!existsSync(file)) {
    console.error(`${sha} has not been verified on this machine (no ${file}): run 'bun run verify' with it checked out`);
    process.exit(1);
  }
  let evidence;
  try {
    evidence = JSON.parse(readFileSync(file, "utf8"));
  } catch {
    console.error(`${file} is not readable evidence`);
    process.exit(1);
  }
  const logSha256 = existsSync(log) ? createHash("sha256").update(readFileSync(log)).digest("hex") : "";
  const verdict = evaluate(evidence, {
    sha,
    tree: git("rev-parse", `${sha}^{tree}`),
    logSha256,
    rehearsal: process.env.DEPLOY_REHEARSAL === "1",
  });
  if (!verdict.ok) {
    console.error(`verification does not allow ${sha}:`);
    for (const problem of verdict.problems) console.error(`  - ${problem}`);
    process.exit(1);
  }
  console.log(JSON.stringify({ ...evidence, checked_at: new Date().toISOString() }));
}

if (import.meta.main) {
  try {
    main(process.argv[2]);
  } catch (error) {
    console.error(`verification gate: ${error.message}`);
    process.exit(1);
  }
}
