/**
 * Builds and serves the app for the E2E suite (Playwright's webServer runs this).
 *
 * The build goes to NEXT_DIST_DIR (.next-e2e, set by playwright.config.ts), never
 * `.next`, which a running `next start` may be serving from. E2E_SKIP_BUILD=1
 * reuses the last E2E build, for quick reruns when only tests changed.
 */
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const appDir = fileURLToPath(new URL("..", import.meta.url));
const nextBin = createRequire(import.meta.url).resolve("next/dist/bin/next");
const port = process.env.PORT ?? "3100";

if (process.env.E2E_SKIP_BUILD !== "1") {
  // `next build` adds its output directory's generated types to tsconfig.json (and
  // reformats the file). That edit only describes this throwaway build, so put the
  // file back exactly as it was.
  const tsconfigPath = `${appDir}tsconfig.json`;
  const tsconfig = readFileSync(tsconfigPath);
  const build = spawnSync(process.execPath, [nextBin, "build"], { cwd: appDir, stdio: "inherit" });
  if (!readFileSync(tsconfigPath).equals(tsconfig)) writeFileSync(tsconfigPath, tsconfig);
  if (build.status !== 0) process.exit(build.status ?? 1);
}

const server = spawn(process.execPath, [nextBin, "start", "-p", port, "-H", "127.0.0.1"], {
  cwd: appDir,
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
