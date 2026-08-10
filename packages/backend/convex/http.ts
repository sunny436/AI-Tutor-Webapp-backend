import { httpRouter } from "convex/server";
import { internal } from "./_generated/api";
import { httpAction } from "./_generated/server";
import { auth } from "./auth";
import { polar } from "./subscriptions";

const http = httpRouter();

auth.addHttpRoutes(http);

// Register the webhook handler at /polar/events
// biome-ignore lint/suspicious/noExplicitAny: <explanation>
polar.registerRoutes(http as any);

// --- Hybrid adapter WEBHOOK PATH: external backend posts results/events here ---
http.route({
  path: "/backend/webhook",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const secret = req.headers.get("x-webhook-secret");
    if (!secret || secret !== process.env.BACKEND_WEBHOOK_SECRET) {
      return new Response("unauthorized", { status: 401 });
    }
    const payload = (await req
      .json()
      .catch(() => ({}))) as Record<string, unknown>;
    const type = typeof payload.type === "string" ? payload.type : "event";

    if (type === "job.result" && typeof payload.jobId === "string") {
      await ctx.runMutation(internal.jobs.complete, {
        // biome-ignore lint/suspicious/noExplicitAny: id validated by Convex
        jobId: payload.jobId as any,
        result: payload.result,
        error: typeof payload.error === "string" ? payload.error : undefined,
      });
    } else {
      await ctx.runMutation(internal.backend.ingestEvent, {
        workspaceId:
          typeof payload.workspaceId === "string"
            ? // biome-ignore lint/suspicious/noExplicitAny: id validated by Convex
              (payload.workspaceId as any)
            : undefined,
        source: "backend",
        type,
        payload,
      });
    }
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }),
});

// --- API key verification (programmatic access) ---
http.route({
  path: "/api/verify-key",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const key = req.headers.get("x-api-key") ?? "";
    const json = (body: unknown, status: number) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });
    if (!key) return json({ valid: false }, 401);
    const buf = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(key),
    );
    const hash = Array.from(new Uint8Array(buf), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
    const found = await ctx.runQuery(internal.apiKeys.resolveByHash, { hash });
    return json({ valid: !!found, ...(found ?? {}) }, found ? 200 : 401);
  }),
});

// --- Long-term conversation memory, read by the Python AI backend ---
//
// The Python side verifies the caller's Convex JWT itself (server.py
// `verify_token`) and sends the resulting subject here. It never forwards a
// user id taken from a request body, so the id arriving here is one Convex
// already vouched for.
//
// Guarded by the shared service key rather than a user session, because the
// caller is a server, not a browser. Compared with `timingSafeEqual` semantics
// in mind: the key is compared in full and a mismatch returns 401 with no hint
// about which part was wrong.
http.route({
  path: "/backend/user-memory",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const json = (body: unknown, status: number) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });

    const expected = process.env.BACKEND_SERVICE_KEY ?? "";
    const supplied = req.headers.get("x-service-key") ?? "";
    // An unset server key must never mean "everything is authorised".
    if (!expected || supplied !== expected) {
      return json({ error: "unauthorized" }, 401);
    }

    const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
    const userId = typeof body.userId === "string" ? body.userId : "";
    if (!userId) return json({ turns: [] }, 200);

    const excludeSessionId =
      typeof body.excludeSessionId === "string" ? body.excludeSessionId : undefined;

    try {
      const turns = await ctx.runQuery(internal.memory.recentTurns, {
        // biome-ignore lint/suspicious/noExplicitAny: id shape validated by Convex
        userId: userId as any,
        excludeSessionId,
      });
      return json({ turns }, 200);
    } catch {
      // A malformed id must not surface as a 500 with internal detail, and the
      // consultation must survive memory being unavailable.
      return json({ turns: [] }, 200);
    }
  }),
});

export default http;
