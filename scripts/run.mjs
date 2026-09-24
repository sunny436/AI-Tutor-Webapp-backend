#!/usr/bin/env bun
/**
 * Repository task runner. Run tasks from the repository root with `bun run <task>`
 * (see package.json). The backend uses its own Python venv (backend/.venv); the frontend
 * is its own Bun workspace (frontend/). Nothing here replaces either tool.
 *
 *   setup          backend venv + requirements-dev, backend/.env from the example; frontend bun install
 *   dev            dev database (Docker), migrations, then API :4000 + web :3000 together
 *   dev:backend    API only (uvicorn --reload on :4000)
 *   dev:frontend   web only (next dev on :3000; expects the API on :4000)
 *   test           backend pytest + frontend typecheck and unit tests (includes the API contract test)
 *   test:e2e       Playwright end-to-end (starts the API from backend/ if none is running on :4100)
 *   lint           ruff (check + format) + biome
 *   build          frontend production build + backend contract check
 *   contract       regenerate docs/openapi.json, then run the frontend contract test against it
 */
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = join(import.meta.dir, "..");
const backend = join(root, "backend");
const frontend = join(root, "frontend");
const app = join(frontend, "apps", "app");
const windows = process.platform === "win32";
const python = join(backend, ".venv", windows ? "Scripts" : "bin", windows ? "python.exe" : "python");

function run(label, command, args, cwd, env = {}) {
  console.log(`\n▶ ${label}: ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, { cwd, stdio: "inherit", env: { ...process.env, ...env } });
  if (result.error) {
    console.error(`✗ ${label}: ${result.error.message}`);
    return 1;
  }
  return result.status ?? 1;
}

function needVenv() {
  if (!existsSync(python)) {
    console.error("✗ backend/.venv is missing. Run `bun run setup` first.");
    process.exit(1);
  }
}

/** Run steps in order, keep going, and fail at the end if any failed. */
function all(steps) {
  const failed = steps.filter((step) => step() !== 0).length;
  if (failed) {
    console.error(`\n✗ ${failed} step(s) failed`);
    process.exit(1);
  }
  console.log("\n✓ all steps passed");
}

/** Start long-running processes together; stop all of them when one exits or on Ctrl+C. */
function together(processes) {
  const children = processes.map(({ label, command, args, cwd, env }) => {
    const child = spawn(command, args, { cwd, stdio: "inherit", env: { ...process.env, ...env } });
    child.on("exit", (code) => {
      console.log(`\n■ ${label} exited (${code ?? "signal"}); stopping the rest`);
      for (const other of children) if (other !== child && other.exitCode === null) other.kill();
      process.exitCode = code ?? 1;
    });
    return child;
  });
  process.on("SIGINT", () => {
    for (const child of children) if (child.exitCode === null) child.kill();
  });
}

const api = () => ({
  label: "api",
  command: python,
  args: ["-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "4000", "--reload"],
  cwd: backend,
});
const web = () => ({ label: "web", command: "bun", args: ["run", "dev"], cwd: frontend });

const tasks = {
  setup() {
    all([
      () =>
        existsSync(python)
          ? 0
          : windows
            ? run("backend venv", "py", ["-3.12", "-m", "venv", ".venv"], backend)
            : run("backend venv", "python3.12", ["-m", "venv", ".venv"], backend),
      () => run("backend deps", python, ["-m", "pip", "install", "-r", "requirements-dev.txt"], backend),
      () => {
        if (!existsSync(join(backend, ".env"))) {
          copyFileSync(join(backend, ".env.example"), join(backend, ".env"));
          console.log("\n▶ created backend/.env from .env.example: add your LLM key (or set LLM_PROVIDER=fake)");
        }
        return 0;
      },
      () => run("frontend deps", "bun", ["install", "--frozen-lockfile"], frontend),
    ]);
  },
  dev() {
    needVenv();
    all([
      () => run("dev database", "docker", ["compose", "-f", "docker-compose.dev.yml", "up", "-d", "--wait"], root),
      () => run("migrations", python, ["-m", "alembic", "upgrade", "head"], backend),
    ]);
    together([api(), web()]);
  },
  "dev:backend"() {
    needVenv();
    together([api()]);
  },
  "dev:frontend"() {
    together([web()]);
  },
  test() {
    needVenv();
    all([
      () => run("backend tests", python, ["-m", "pytest", "-o", "addopts=", "-q", "-ra"], backend),
      () => run("frontend typecheck", "bun", ["run", "typecheck"], frontend),
      () => run("frontend tests", "bun", ["run", "test"], frontend),
    ]);
  },
  "test:e2e"() {
    needVenv();
    all([() => run("end-to-end", "bun", ["run", "test:e2e"], app)]);
  },
  lint() {
    needVenv();
    all([
      () => run("ruff check", python, ["-m", "ruff", "check", "."], backend),
      () => run("ruff format", python, ["-m", "ruff", "format", "--check", "."], backend),
      () => run("biome", "bun", ["run", "lint"], frontend),
    ]);
  },
  build() {
    needVenv();
    all([
      () => run("API contract current", python, ["scripts/export_openapi.py", "--check"], backend),
      () => run("frontend build", "bun", ["run", "build"], frontend),
    ]);
  },
  contract() {
    needVenv();
    all([
      () => run("regenerate docs/openapi.json", python, ["scripts/export_openapi.py"], backend),
      () => run("frontend contract test", "bun", ["test", "src/lib/api/routes.test.ts"], app),
    ]);
  },
};

const name = process.argv[2];
if (!name || !(name in tasks)) {
  console.error(`usage: bun run <task>\ntasks: ${Object.keys(tasks).join(", ")}, deploy, rollback`);
  process.exit(2);
}
tasks[name]();
