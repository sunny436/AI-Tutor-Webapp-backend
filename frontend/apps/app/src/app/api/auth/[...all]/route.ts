/**
 * `/api/auth/*`: Better Auth (lib/auth). Only the routes in lib/auth/routes.ts reach it; every
 * JSON answer leaves without its session token (page code never holds one).
 */

import { authRoute, withoutTokens } from "@/lib/auth/routes";
import { getAuth } from "@/lib/auth/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const NOT_FOUND = { error: { code: "not_found" } };

async function handle(request: Request): Promise<Response> {
  if (!authRoute(request.method, new URL(request.url).pathname)) {
    return Response.json(NOT_FOUND, { status: 404, headers: { "Cache-Control": "no-store" } });
  }
  const response = await getAuth().auth.handler(request);
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) return response;
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return new Response(text, { status: response.status, headers: response.headers });
  }
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("Cache-Control", "no-store");
  return new Response(JSON.stringify(withoutTokens(body)), { status: response.status, headers });
}

export { handle as GET, handle as POST };
