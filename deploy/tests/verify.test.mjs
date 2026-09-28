import { describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REQUIRED_JOBS } from "../ci-gate.mjs";
import { summarize, verify, writeAtomic } from "../verify.mjs";

const SHA = "1".repeat(40);
const TREE = "2".repeat(40);

/** A fake repository: `status` and `head` can change between calls to simulate edits. */
function fakeGit({ status = [""], head = [SHA], fsck = 0 } = {}) {
  let statusCalls = 0;
  let headCalls = 0;
  return (args) => {
    if (args[0] === "status") return { code: 0, out: status[Math.min(statusCalls++, status.length - 1)] };
    if (args[0] === "rev-parse" && args[1] === "HEAD") return { code: 0, out: head[Math.min(headCalls++, head.length - 1)] };
    if (args[0] === "rev-parse") return { code: 0, out: TREE };
    if (args[0] === "fsck") return { code: fsck, out: "" };
    return { code: 1, out: "" };
  };
}
const passingSteps = () => REQUIRED_JOBS.flatMap((job) => [{ job, command: "true", exit: 0 }]);
const container = (steps) => async () => ({ steps, runner: { os: "Ubuntu 24.04" }, images: {}, log: Buffer.from("log") });

async function run(options) {
  const written = [];
  let ran = false;
  const evidence = await verify({
    git: options.git ?? fakeGit(),
    runContainer: async (input) => {
      ran = true;
      return (options.container ?? container(passingSteps()))(input);
    },
    writeEvidence: (sha, record) => written.push({ sha, record }),
    now: () => "2026-09-28T00:00:00Z",
    machine: "test",
    operator: "tester",
  });
  return { evidence, written, ran };
}

describe("bun run verify", () => {
  test("a passing run records success for this commit and tree", async () => {
    const { evidence, written } = await run({});
    expect(evidence).toMatchObject({ sha: SHA, tree: TREE, result: "success", source: "local" });
    expect(written).toHaveLength(1);
  });

  test("a dirty working tree is refused before anything runs", async () => {
    let ran = false;
    await expect(
      verify({
        git: fakeGit({ status: [" M backend/app/main.py"] }),
        runContainer: async () => {
          ran = true;
        },
        writeEvidence: () => {},
        now: () => "",
      }),
    ).rejects.toThrow("uncommitted or untracked");
    expect(ran).toBe(false);
  });

  test("a repository git fsck complains about is refused", async () => {
    await expect(run({ git: fakeGit({ fsck: 1 }) })).rejects.toThrow("git fsck");
  });

  test("HEAD moving while it runs records nothing", async () => {
    await expect(run({ git: fakeGit({ head: [SHA, "3".repeat(40)] }) })).rejects.toThrow("changed while it was being verified");
  });

  test("an edit made while it runs records nothing", async () => {
    await expect(run({ git: fakeGit({ status: ["", " M frontend/package.json"] }) })).rejects.toThrow("changed while it was being verified");
  });

  test("a failed command fails its job and the verification, and the evidence says so", async () => {
    const steps = passingSteps();
    steps[1] = { ...steps[1], exit: 2 };
    const { evidence } = await run({ container: container(steps) });
    expect(evidence.result).toBe("failure");
    expect(evidence.jobs[1].conclusion).toBe("failure");
  });

  test("a job that never ran (the runner died) is a failure", async () => {
    const { evidence } = await run({ container: container(passingSteps().slice(0, 2)) });
    expect(evidence.result).toBe("failure");
    expect(summarize(passingSteps().slice(0, 2)).jobs[2]).toMatchObject({ conclusion: "failure", steps: [] });
  });

  test("a skipped command is not a pass", () => {
    const steps = [...passingSteps(), { job: REQUIRED_JOBS[0], command: "later", exit: null, skipped: true }];
    expect(summarize(steps).result).toBe("failure");
  });

  test("evidence is written whole or not at all", () => {
    const directory = mkdtempSync(join(tmpdir(), "verify-test-"));
    const file = join(directory, "evidence.json");
    writeAtomic(file, "{}");
    expect(readFileSync(file, "utf8")).toBe("{}");
    expect(readdirSync(directory)).toEqual(["evidence.json"]);
  });

  test("it takes no options: nothing can skip or change what runs", () => {
    const result = spawnSync("bun", [join(import.meta.dir, "..", "verify.mjs"), "--skip-tests"], { encoding: "utf8" });
    expect(result.status).toBe(2);
    const source = readFileSync(join(import.meta.dir, "..", "verify.mjs"), "utf8");
    expect(source).not.toMatch(/process\.env\.[A-Z_]/);
    expect(existsSync(join(import.meta.dir, "..", "verify", "run-ci.sh"))).toBe(true);
  });
});
