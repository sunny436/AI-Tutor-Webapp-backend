import { describe, expect, test } from "bun:test";
import { REQUIRED_JOBS, evaluate } from "../ci-gate.mjs";

const run = (name, id, status, conclusion) => ({ name, id, status, conclusion, html_url: `https://ci/${id}` });
const allGreen = () => REQUIRED_JOBS.map((name, i) => run(name, i + 1, "completed", "success"));

describe("CI gate", () => {
  test("passes only when every required job completed with success", () => {
    const verdict = evaluate(allGreen());
    expect(verdict.ok).toBe(true);
    expect(verdict.jobs.map((j) => j.name)).toEqual(REQUIRED_JOBS);
  });

  test("a failed job refuses the deploy", () => {
    const runs = allGreen();
    runs[1] = run(REQUIRED_JOBS[1], 2, "completed", "failure");
    expect(evaluate(runs)).toMatchObject({ ok: false, problems: [`${REQUIRED_JOBS[1]}: failure`] });
  });

  test("a job still running refuses the deploy", () => {
    const runs = allGreen();
    runs[0] = run(REQUIRED_JOBS[0], 1, "in_progress", null);
    expect(evaluate(runs).ok).toBe(false);
  });

  test("a required job that never ran (e.g. removed from CI) refuses the deploy", () => {
    const runs = allGreen().filter((r) => r.name !== REQUIRED_JOBS[2]);
    expect(evaluate(runs)).toMatchObject({ ok: false, problems: [`${REQUIRED_JOBS[2]}: did not run`] });
  });

  test("no check runs at all refuses the deploy", () => {
    expect(evaluate([]).ok).toBe(false);
  });

  test("the latest run of a job wins: a green re-run passes, a red re-run fails", () => {
    const rerunGreen = [...allGreen(), run(REQUIRED_JOBS[0], 0, "completed", "failure")];
    expect(evaluate(rerunGreen).ok).toBe(true);
    const rerunRed = [...allGreen(), run(REQUIRED_JOBS[0], 99, "completed", "failure")];
    expect(evaluate(rerunRed).ok).toBe(false);
  });

  test("skipped, cancelled or neutral conclusions are not success", () => {
    for (const conclusion of ["skipped", "cancelled", "neutral", "timed_out"]) {
      const runs = allGreen();
      runs[2] = run(REQUIRED_JOBS[2], 3, "completed", conclusion);
      expect(evaluate(runs).ok).toBe(false);
    }
  });
});

describe("CI workflow", () => {
  test("every job the gate requires exists in .github/workflows/ci.yml under that exact name", async () => {
    const workflow = await Bun.file(new URL("../../.github/workflows/ci.yml", import.meta.url)).text();
    for (const name of REQUIRED_JOBS) expect(workflow).toContain(`name: ${name}\n`);
  });
});
