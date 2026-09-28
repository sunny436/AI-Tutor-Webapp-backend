/**
 * `bun run verify` is only a stand-in for CI while it runs exactly what CI runs. This fails when
 * .github/workflows/ci.yml and deploy/verify/ drift apart: a job, a command (in order), a working
 * directory, an env value, a service image or its settings.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { REQUIRED_JOBS } from "../ci-gate.mjs";

const ROOT = join(import.meta.dir, "..", "..");
const ci = Bun.YAML.parse(readFileSync(join(ROOT, ".github/workflows/ci.yml"), "utf8"));
const runner = readFileSync(join(ROOT, "deploy/verify/run-ci.sh"), "utf8");
const compose = Bun.YAML.parse(readFileSync(join(ROOT, "deploy/verify/compose.yml"), "utf8"));

/** CI: every `run:` line of a job, with the directory it runs in. */
function ciSteps(job) {
  const base = job.defaults?.run?.["working-directory"] ?? ".";
  return job.steps
    .filter((step) => typeof step.run === "string")
    .flatMap((step) =>
      step.run
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((command) => ({ dir: step["working-directory"] ?? base, command })),
    );
}

/** The runner: its `job` sections, each with its `step` lines and `export` values. */
function runnerJobs() {
  const jobs = new Map();
  let current = null;
  for (const line of runner.split("\n")) {
    const job = /^job "(.+)" \S+$/.exec(line);
    if (job) {
      current = { steps: [], env: {} };
      jobs.set(job[1], current);
      continue;
    }
    if (!current) continue;
    const step = /^step (\S+) (?:"(.*)"|'(.*)')$/.exec(line);
    if (step) current.steps.push({ dir: step[1], command: step[2] ?? step[3] });
    const exported = /^export (.+)$/.exec(line);
    if (exported && !exported[1].startsWith("PATH=")) {
      for (const pair of exported[1].split(/\s+/)) {
        const [key, ...value] = pair.split("=");
        current.env[key] = value.join("=");
      }
    }
  }
  return jobs;
}

const jobs = runnerJobs();

describe("local verification runs exactly what CI runs", () => {
  test("the same three jobs, by name, as ci-gate.mjs reports", () => {
    expect(Object.values(ci.jobs).map((job) => job.name)).toEqual(REQUIRED_JOBS);
    expect([...jobs.keys()]).toEqual(REQUIRED_JOBS);
  });

  for (const job of Object.values(ci.jobs)) {
    test(`${job.name}: the same commands, in the same order and directories`, () => {
      expect(jobs.get(job.name)?.steps).toEqual(ciSteps(job));
    });

    test(`${job.name}: CI's env is set`, () => {
      for (const [key, value] of Object.entries(job.env ?? {})) expect(jobs.get(job.name)?.env[key]).toBe(String(value));
    });

    test(`${job.name}: the same service images and settings`, () => {
      for (const [name, service] of Object.entries(job.services ?? {})) {
        expect(compose.services[name]?.image).toBe(service.image);
        for (const [key, value] of Object.entries(service.env ?? {})) expect(compose.services[name].environment[key]).toBe(String(value));
      }
    });
  }

  test("the runtimes are CI's: Python 3.12, and Node and Bun from the commit's pin files", () => {
    for (const job of Object.values(ci.jobs)) {
      for (const step of job.steps) {
        if (step.uses?.startsWith("actions/setup-python")) expect(String(step.with["python-version"])).toBe("3.12");
        if (step.uses?.startsWith("actions/setup-node")) expect(step.with["node-version-file"]).toBe(".node-version");
        if (step.uses?.startsWith("oven-sh/setup-bun")) expect(step.with["bun-version-file"]).toBe(".bun-version");
      }
    }
    const dockerfile = readFileSync(join(ROOT, "deploy/verify/Dockerfile"), "utf8");
    expect(dockerfile).toContain("python3.12");
    expect(dockerfile).toMatch(/^FROM ubuntu:24\.04@sha256:[0-9a-f]{64}$/m);
    const verify = readFileSync(join(ROOT, "deploy/verify.mjs"), "utf8");
    expect(verify).toContain(".node-version");
    expect(verify).toContain(".bun-version");
  });
});
