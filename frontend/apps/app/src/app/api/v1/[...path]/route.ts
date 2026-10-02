/**
 * `/api/v1/*` — the browser's only door to the chat API. All of the logic (and its
 * tests) lives in `lib/server/proxy-core.ts`; this file only wires it to Next.js.
 */

import { apiBaseUrl, authSecret } from "@/lib/server/config";
import { proxyRequest } from "@/lib/server/proxy-core";

// Reads a cookie and streams: never prerendered, never cached, Node runtime.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ path?: string[] }> };

async function handle(request: Request, { params }: Context): Promise<Response> {
  return proxyRequest(request, (await params).path ?? [], { apiBaseUrl: apiBaseUrl(), cookieSecret: authSecret() });
}

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST, handle as PUT };
