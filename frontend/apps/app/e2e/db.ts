import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

/**
 * One SQL statement against the E2E API's own database, for the rare spec that needs a state no
 * API can make (no study greeting live). It runs through the local backend's venv and Settings, so
 * it reaches exactly the database the E2E API uses (backend/.env locally, the defaults in CI).
 * `backendDir` is null when this machine has no local backend: specs skip themselves then.
 */
const python = process.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python");
const repoBackend = join(__dirname, "..", "..", "..", "..", "backend");
const requested = process.env.E2E_BACKEND_DIR;
export const backendDir =
  requested === "none" ? null : requested || (existsSync(join(repoBackend, python)) ? repoBackend : null);

const SCRIPT = `
import asyncio, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.settings import Settings

async def main():
    engine = create_async_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text(sys.argv[1]))
    await engine.dispose()

asyncio.run(main())
`;

export function sql(statement: string): void {
  if (!backendDir) throw new Error("no local backend to reach the database through");
  execFileSync(join(backendDir, python), ["-c", SCRIPT, statement], { cwd: backendDir, stdio: "pipe" });
}
