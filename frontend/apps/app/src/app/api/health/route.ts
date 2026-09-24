/**
 * `/api/health`: the web server is up, and (to local callers only) the release it runs.
 * Deploys and `bun run status` compare it with the API's `/health` release.
 */
import { healthBody, runningRelease } from "@/lib/server/release";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request): Response {
  return Response.json(healthBody(request.headers, runningRelease()), {
    headers: { "Cache-Control": "no-store" },
  });
}
