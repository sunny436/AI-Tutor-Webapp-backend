/**
 * The browser's only door to the central AI API.
 *
 * The Python backend it replaces was called DIRECTLY from the browser, which was
 * fine because that backend verified a Convex JWT itself. The central API
 * authenticates with an application-level key instead, and that changes two
 * things which together make a direct call unshippable:
 *
 *   1. A key the browser holds is public. It is in the bundle, in devtools, in
 *      every visitor's cache. Ours would be spendable by anyone who opened the
 *      page — the same class of hole as the anonymous /chat endpoint closed
 *      earlier today, just harder to notice.
 *
 *   2. `user_id` is an email address. If the browser composes the request, it
 *      chooses that value, so anyone could ask for anybody else's medical
 *      conversation by typing their address. Authentication has to happen where
 *      the user cannot edit it.
 *
 * So the key stays here, and the identity is read from the VERIFIED Convex
 * session. Whatever the request body claims about who the user is, is ignored.
 */

import { api } from "@v1/backend/convex/_generated/api";
import { convexAuthNextjsToken } from "@convex-dev/auth/nextjs/server";
import { ConvexHttpClient } from "convex/browser";
import { type NextRequest, NextResponse } from "next/server";

import {
  buildCentralRequest,
  centralConfig,
  centralConfigProblem,
  normalizeCentralResponse,
  type Principal,
} from "@/lib/consult/central";

// The Convex token is read from a cookie, so this must not be prerendered.
export const dynamic = "force-dynamic";

/**
 * Who is calling, according to the session — never according to the body.
 *
 * Uses the existing `api.users.getUser` query rather than a new one, because
 * adding a Convex function needs a deploy and this needs none. It returns the
 * whole user record, which is more than required, but it is one round trip and
 * it is already the query the dashboard uses to identify the signed-in person.
 */
async function resolvePrincipal(): Promise<Principal | null> {
  const token = await convexAuthNextjsToken();
  if (!token) return null;

  const convexUrl = process.env.NEXT_PUBLIC_CONVEX_URL;
  if (!convexUrl) throw new Error("NEXT_PUBLIC_CONVEX_URL is not set");

  const client = new ConvexHttpClient(convexUrl);
  client.setAuth(token);

  const user = await client.query(api.users.getUser, {});
  if (!user?._id) return null;

  return {
    userId: String(user._id),
    email: typeof user.email === "string" ? user.email : "",
    phone: typeof user.phone === "string" ? user.phone : "",
  };
}

export async function POST(request: NextRequest) {
  const problem = centralConfigProblem();
  if (problem) {
    // A misconfiguration must not read like the assistant refusing to answer.
    return NextResponse.json(
      { error: `The AI service is ${problem}.` },
      { status: 503 },
    );
  }

  let principal: Principal | null;
  try {
    principal = await resolvePrincipal();
  } catch (error) {
    console.error("[consult] could not resolve the session:", error);
    return NextResponse.json({ error: "Could not verify your session." }, { status: 500 });
  }
  if (!principal) {
    return NextResponse.json({ error: "Please sign in." }, { status: 401 });
  }

  const incoming = (await request.json().catch(() => null)) as {
    problem?: string;
    freeText?: string;
    answers?: Record<string, never>;
    conversationId?: string;
    context?: never;
  } | null;
  if (!incoming) {
    return NextResponse.json({ error: "Malformed request." }, { status: 400 });
  }

  const payload = buildCentralRequest({
    principal,
    message: incoming.problem ?? "",
    freeText: incoming.freeText ?? "",
    answers: incoming.answers ?? {},
    conversationId: incoming.conversationId ?? "",
    context: incoming.context ?? null,
  });

  let upstream: Response;
  try {
    upstream = await fetch(centralConfig.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${centralConfig.apiKey}`,
      },
      body: JSON.stringify(payload),
      // A full consultation can take a while; do not let a default cut it off.
      signal: AbortSignal.timeout(180_000),
    });
  } catch (error) {
    console.error("[consult] central API unreachable:", error);
    return NextResponse.json(
      { error: "Could not reach the AI service. Please try again." },
      { status: 502 },
    );
  }

  const bodyText = await upstream.text();
  if (!upstream.ok) {
    // Log the upstream body, return a clean message. The response can carry
    // provider detail the user has no use for and should not be shown.
    console.error(`[consult] central API ${upstream.status}: ${bodyText.slice(0, 500)}`);
    return NextResponse.json(
      { error: "The AI service returned an error. Please try again." },
      { status: 502 },
    );
  }

  try {
    const parsed = JSON.parse(bodyText);
    return NextResponse.json(
      normalizeCentralResponse(parsed, incoming.context ?? null),
    );
  } catch (error) {
    // Includes the "reply not understood" case, whose message names the keys
    // that actually arrived — the one thing needed to finish the mapping.
    console.error(
      `[consult] could not read the reply: ${(error as Error).message}\n` +
        `raw: ${bodyText.slice(0, 800)}`,
    );
    return NextResponse.json(
      { error: "The AI service sent something this app could not read." },
      { status: 502 },
    );
  }
}
