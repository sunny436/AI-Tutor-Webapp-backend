import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The files a content key leaves out (deploy/server/lib.sh TEST_FILES): changing only these must
// never rebuild or restart production.
const lib = readFileSync(join(import.meta.dir, "..", "server", "lib.sh"), "utf-8");
const pattern = lib.match(/^TEST_FILES='([^']+)'$/m)?.[1];

/** The paths `grep -vE "$TEST_FILES"` keeps, from `git ls-tree -r` lines, as lib.sh runs it. */
function kept(paths) {
  const lines = paths.map((path) => `100644 blob ${"a".repeat(40)}\t${path}`).join("\n");
  const result = spawnSync("bash", ["-c", 'grep -vE "$TEST_FILES" || true'], {
    input: `${lines}\n`,
    env: { ...process.env, TEST_FILES: pattern },
    encoding: "utf-8",
  });
  return result.stdout.split("\n").filter(Boolean).map((line) => line.split("\t")[1]);
}

test("tests, e2e and the production smoke are not part of any content key", () => {
  expect(pattern).toBeTruthy();
  expect(
    kept([
      "backend/tests/test_auth.py",
      "frontend/apps/app/e2e/motion.e2e.ts",
      "frontend/apps/app/src/lib/greeting.test.ts",
      "frontend/apps/app/smoke/desktop.smoke.ts",
      "frontend/apps/app/smoke/support.ts",
      "frontend/apps/app/playwright.smoke.config.ts",
    ]),
  ).toEqual([]);
});

test("the code that is built and served stays in", () => {
  const code = [
    "backend/app/main.py",
    "frontend/apps/app/src/app/layout.tsx",
    "frontend/apps/app/src/features/chat/composer.tsx",
    "frontend/apps/app/package.json",
    "frontend/apps/app/next.config.mjs",
    "frontend/packages/ui/src/globals.css",
  ];
  expect(kept(code)).toEqual(code);
});
