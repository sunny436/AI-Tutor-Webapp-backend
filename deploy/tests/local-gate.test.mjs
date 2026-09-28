import { describe, expect, test } from "bun:test";

import { REQUIRED_JOBS } from "../ci-gate.mjs";
import { EVIDENCE_VERSION, evaluate } from "../local-gate.mjs";

const SHA = "a".repeat(40);
const TREE = "b".repeat(40);
const LOG = "c".repeat(64);

const passing = () => ({
  version: EVIDENCE_VERSION,
  sha: SHA,
  tree: TREE,
  source: "local",
  result: "success",
  log_sha256: LOG,
  jobs: REQUIRED_JOBS.map((name) => ({ name, conclusion: "success", steps: [{ command: "true", exit: 0 }] })),
});
const check = (evidence, overrides = {}) => evaluate(evidence, { sha: SHA, tree: TREE, logSha256: LOG, ...overrides });

describe("verification gate", () => {
  test("passes only evidence for this exact commit and tree, with every job green", () => {
    expect(check(passing())).toEqual({ ok: true, problems: [] });
  });

  test("no evidence refuses", () => {
    expect(check(undefined).ok).toBe(false);
  });

  test("evidence for another commit refuses (an amended or different commit)", () => {
    expect(check({ ...passing(), sha: "d".repeat(40) }).ok).toBe(false);
  });

  test("evidence for another tree refuses", () => {
    expect(check(passing(), { tree: "e".repeat(40) }).ok).toBe(false);
  });

  test("a failed job refuses", () => {
    const evidence = passing();
    evidence.jobs[2] = { ...evidence.jobs[2], conclusion: "failure" };
    expect(check({ ...evidence, result: "failure" })).toMatchObject({ ok: false });
  });

  test("a failed step refuses even if the job claims success", () => {
    const evidence = passing();
    evidence.jobs[0].steps.push({ command: "python -m pytest", exit: 1 });
    expect(check(evidence).ok).toBe(false);
  });

  test("a job that never ran refuses", () => {
    const evidence = passing();
    evidence.jobs = evidence.jobs.slice(0, 2);
    expect(check(evidence).problems).toContain(`${REQUIRED_JOBS[2]}: did not run`);
  });

  test("a log that is not the one the evidence names refuses", () => {
    expect(check(passing(), { logSha256: "f".repeat(64) }).ok).toBe(false);
    expect(check(passing(), { logSha256: "" }).ok).toBe(false);
  });

  test("rehearsal evidence never releases to a real host, only in rehearsal mode", () => {
    const rehearsal = { ...passing(), rehearsal: true, log_sha256: "-", jobs: REQUIRED_JOBS.map((name) => ({ name, conclusion: "success" })) };
    expect(check(rehearsal, { logSha256: "" }).problems).toContain("rehearsal evidence cannot release to a real host");
    expect(check(rehearsal, { logSha256: "", rehearsal: true }).ok).toBe(true);
  });

  test("an unknown evidence version refuses", () => {
    expect(check({ ...passing(), version: 2 }).ok).toBe(false);
  });
});
