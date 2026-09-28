#!/usr/bin/env bun
/**
 * `bun run verify` (optional; never required by a deploy): run the three CI jobs, command for
 * command (deploy/verify/run-ci.sh), in a Linux container on `git archive` of the commit checked
 * out here, and record the result in .deploy/verified/. The way to run CI while GitHub Actions
 * has no minutes. It takes no options and reads no environment: what runs is decided by the
 * commit being verified, nothing else.
 *
 *   1. the working tree is clean; HEAD is the commit; `git fsck --strict` finds nothing wrong
 *   2. the container image: Ubuntu 24.04 + Python 3.12 + the commit's .node-version/.bun-version
 *      + the system libraries of the commit's Playwright version
 *   3. `git archive <commit>` into the container with CI's services (pgvector, Mailpit); the
 *      container sees only the commit's files, no ignored file, secret or local install
 *   4. HEAD and the tree are unchanged afterwards (nothing was edited meanwhile)
 *   5. .deploy/verified/<commit>.json + .log, written atomically; exit 0 only if every job passed
 *
 * About 30-35 minutes: the jobs run at the same time, then the E2E suite (about 23 minutes) on a
 * quiet machine. The first run also builds the image and fills the download cache.
 */
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createWriteStream, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { hostname, tmpdir } from "node:os";
import { join } from "node:path";

import { REQUIRED_JOBS } from "./ci-gate.mjs";

// Where the results go (git-ignored), and their format.
export const EVIDENCE_DIR = ".deploy/verified";
export const EVIDENCE_VERSION = 1;

/** Write `path` so that it is either absent or complete, never half-written. */
export function writeAtomic(path, content) {
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, content);
  renameSync(temporary, path);
}

/** The jobs, from the runner's step results: a job passes only if it ran and every step passed. */
export function summarize(steps) {
  const jobs = REQUIRED_JOBS.map((name) => {
    const own = steps.filter((step) => step.job === name);
    const passed = own.length > 0 && own.every((step) => step.exit === 0 && !step.skipped);
    return { name, conclusion: passed ? "success" : "failure", steps: own };
  });
  return { jobs, result: jobs.every((job) => job.conclusion === "success") ? "success" : "failure" };
}

/**
 * The verification, with its outside world injected (tests replace it):
 *   git(args) -> { code, out }           runContainer({ sha, input }) -> { steps, runner, images, log }
 *   writeEvidence(sha, evidence, log)    now() -> ISO time
 */
export async function verify({ git, runContainer, writeEvidence, now, machine, operator }) {
  const clean = () => git(["status", "--porcelain", "--untracked-files=normal"]).out === "";
  if (!clean()) throw new Error("the working tree has uncommitted or untracked changes: verify a commit, not a working tree");
  const sha = git(["rev-parse", "HEAD"]).out;
  const tree = git(["rev-parse", "HEAD^{tree}"]).out;
  if (git(["fsck", "--strict", "--no-dangling"]).code !== 0) throw new Error("git fsck found a problem in this repository; repair it before verifying");

  const started = now();
  const run = await runContainer({ sha });
  if (git(["rev-parse", "HEAD"]).out !== sha || git(["rev-parse", "HEAD^{tree}"]).out !== tree || !clean()) {
    throw new Error("the checkout changed while it was being verified; nothing was recorded");
  }
  const { jobs, result } = summarize(run.steps);
  const evidence = {
    version: EVIDENCE_VERSION,
    sha,
    tree,
    source: "local",
    result,
    jobs,
    started_at: started,
    finished_at: now(),
    machine,
    operator,
    runner: run.runner,
    images: run.images,
    log_sha256: createHash("sha256").update(run.log).digest("hex"),
  };
  writeEvidence(sha, evidence, run.log);
  return evidence;
}

// ------------------------------------------------------------------ the real world

function sh(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, ...options });
  return { code: result.status ?? 1, out: (result.stdout ?? "").trim(), err: (result.stderr ?? "").trim() };
}

function must(result, what) {
  if (result.code !== 0) throw new Error(`${what} failed: ${result.err || result.out}`);
  return result.out;
}

/** Stream a command's output to the console and the log, collecting the runner's result lines. */
function stream(command, args, env, logFile) {
  return new Promise((resolve, reject) => {
    const log = createWriteStream(logFile, { flags: "a" });
    const steps = [];
    let runner = null;
    let pending = "";
    const child = spawn(command, args, { env: { ...process.env, ...env } });
    const take = (chunk) => {
      process.stdout.write(chunk);
      log.write(chunk);
      pending += chunk.toString("utf8");
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        const text = line.replace(/\r$/, "");
        if (text.startsWith("@@STEP ")) steps.push(JSON.parse(text.slice(7)));
        if (text.startsWith("@@RUNNER ")) runner = JSON.parse(text.slice(9));
      }
    };
    child.stdout.on("data", take);
    child.stderr.on("data", take);
    child.on("error", reject);
    child.on("close", (code) => log.end(() => resolve({ code, steps, runner })));
  });
}

async function runContainer({ sha, repo }) {
  must(sh("docker", ["info", "--format", "{{.ServerVersion}}"]), "Docker (is it running?)");
  const work = mkdtempSync(join(tmpdir(), "aichat-verify-"));
  const input = join(work, "in");
  const context = join(work, "image");
  mkdirSync(input);
  mkdirSync(context);
  const show = (path) => must(sh("git", ["-C", repo, "show", `${sha}:${path}`]), `git show ${path}`);
  const node = show(".node-version").trim();
  const bun = show(".bun-version").trim();
  const playwright = /"playwright-core": \["playwright-core@([0-9][^"]*)"/.exec(show("frontend/bun.lock"))?.[1];
  if (!playwright) throw new Error("frontend/bun.lock pins no playwright-core version");
  must(sh("git", ["-C", repo, "archive", "--format=tar", "-o", join(input, "src.tar"), sha]), "git archive");
  writeFileSync(join(input, "run-ci.sh"), show("deploy/verify/run-ci.sh"));
  writeFileSync(join(input, "compose.yml"), show("deploy/verify/compose.yml"));
  const dockerfile = show("deploy/verify/Dockerfile");
  writeFileSync(join(context, "Dockerfile"), dockerfile);
  const tag = `aichat-verify:${createHash("sha256").update(`${dockerfile}\n${node}\n${bun}\n${playwright}`).digest("hex").slice(0, 16)}`;
  const logFile = join(work, "verify.log");
  writeFileSync(logFile, `verify ${sha}\n`);

  console.log(`==> image ${tag} (Ubuntu 24.04, Python 3.12, Node ${node}, Bun ${bun}, Playwright ${playwright})`);
  const buildArgs = [`NODE_VERSION=${node}`, `BUN_VERSION=${bun}`, `PLAYWRIGHT_VERSION=${playwright}`].flatMap((arg) => ["--build-arg", arg]);
  must(sh("docker", ["build", "--quiet", ...buildArgs, "-t", tag, context], { stdio: ["ignore", "pipe", "inherit"] }), "docker build");
  must(sh("docker", ["volume", "create", "aichat-verify-cache"]), "the download cache volume");
  const project = `aichat-verify-${sha.slice(0, 12)}-${process.pid}`;
  const env = { VERIFY_IMAGE: tag, VERIFY_INPUT: input };
  const compose = ["compose", "-p", project, "-f", join(input, "compose.yml")];
  try {
    must(sh("docker", [...compose, "up", "-d", "--wait", "postgres", "mailpit"], { env: { ...process.env, ...env } }), "starting PostgreSQL and Mailpit");
    console.log(`==> the three CI jobs on git archive ${sha.slice(0, 12)} (log: ${logFile})`);
    const run = await stream("docker", [...compose, "run", "--rm", "runner"], env, logFile);
    const digest = (image) => sh("docker", ["image", "inspect", image, "--format", "{{index .RepoDigests 0}}"]).out || image;
    const images = {
      runner: sh("docker", ["image", "inspect", tag, "--format", "{{.Id}}"]).out,
      postgres: digest("pgvector/pgvector:pg16"),
      mailpit: digest("axllent/mailpit"),
    };
    return { steps: run.steps, runner: run.runner, images, log: readFileSync(logFile) };
  } finally {
    sh("docker", [...compose, "down", "-v", "--remove-orphans"], { env: { ...process.env, ...env } });
    rmSync(work, { recursive: true, force: true });
  }
}

async function main(args) {
  if (args.length > 0) {
    console.error("usage: bun run verify   (no options: it verifies the commit checked out here, as CI would)");
    process.exit(2);
  }
  const repo = must(sh("git", ["rev-parse", "--show-toplevel"]), "git rev-parse");
  const git = (gitArgs) => sh("git", ["-C", repo, ...gitArgs]);
  const directory = join(repo, EVIDENCE_DIR);
  const evidence = await verify({
    git,
    runContainer: ({ sha }) => runContainer({ sha, repo }),
    writeEvidence: (sha, record, log) => {
      mkdirSync(directory, { recursive: true });
      writeAtomic(join(directory, `${sha}.log`), log);
      writeAtomic(join(directory, `${sha}.json`), `${JSON.stringify(record, null, 1)}\n`);
    },
    now: () => new Date().toISOString(),
    machine: hostname(),
    operator: git(["config", "user.name"]).out || "unknown",
  });
  console.log(`\n==> ${evidence.sha}: ${evidence.result.toUpperCase()}`);
  for (const job of evidence.jobs) {
    const failed = job.steps.find((step) => step.exit !== 0);
    console.log(`    ${job.conclusion === "success" ? "ok  " : "FAIL"} ${job.name}${failed ? `  (${failed.skipped ? "not reached" : `"${failed.command}" exited ${failed.exit}`})` : ""}`);
  }
  console.log(`    evidence: ${EVIDENCE_DIR}/${evidence.sha}.json`);
  process.exit(evidence.result === "success" ? 0 : 1);
}

if (import.meta.main) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(`verify: ${error.message}`);
    process.exit(1);
  });
}
