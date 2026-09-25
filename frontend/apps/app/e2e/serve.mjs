/**
 * Builds and serves the app for the E2E suite (Playwright's webServer runs this).
 *
 * The build goes to NEXT_DIST_DIR (.next-e2e, set by playwright.config.ts), never
 * `.next`, which a running `next start` may be serving from. E2E_SKIP_BUILD=1
 * reuses the last E2E build, for quick reruns when only tests changed.
 *
 * One build, TWO servers: PORT as production runs it (PREVIEW_FEATURES forced
 * off), and PREVIEW_PORT with preview features on (lib/preview.ts reads the
 * switch per request, so the same build serves both). The suite checks that the
 * first shows no preview UI and that the second's preview UI is accessible.
 */
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const appDir = fileURLToPath(new URL("..", import.meta.url));
const nextBin = createRequire(import.meta.url).resolve("next/dist/bin/next");
const port = process.env.PORT ?? "3100";
const previewPort = process.env.PREVIEW_PORT ?? "3101";

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

const start = (listen, preview) =>
  spawn(process.execPath, [nextBin, "start", "-p", listen, "-H", "127.0.0.1"], {
    cwd: appDir,
    stdio: "inherit",
    env: { ...process.env, PREVIEW_FEATURES: preview ? "1" : "0" },
  });
const servers = [start(port, false), start(previewPort, true)];
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    for (const server of servers) server.kill(signal);
  });
}
// Either one stopping ends the run: a suite must not go on with half its servers.
for (const server of servers) {
  server.on("exit", (code) => {
    for (const other of servers) if (other !== server) other.kill();
    process.exit(code ?? 0);
  });
}
