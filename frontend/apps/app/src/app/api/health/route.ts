/**
 * `/api/health`: the web server is up, and (to local callers only) the release it runs.
 * Deploys and `bun run status` compare it with the API's `/health` release.
 */
import { authDatabaseOk } from "@/lib/auth/server";
import { healthBody, isLocalRequest, runningRelease } from "@/lib/server/release";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  const body = healthBody(request.headers, runningRelease());
  // Locally only: whether Better Auth reaches its tables (role, password, database). The deploy's
  // smoke requires "ok" (deploy/server/update.sh).
  if (isLocalRequest(request.headers)) body.auth = (await authDatabaseOk()) ? "ok" : "unavailable";
  return Response.json(body, { headers: { "Cache-Control": "no-store" } });
}
