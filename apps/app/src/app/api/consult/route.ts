/**
 * The browser's only door to whichever AI is answering.
 *
 * WHY THE BROWSER NO LONGER CARRIES THE TOKEN
 *
 * It used to. The page read `useAuthToken()` and posted straight to the Python
 * backend. That produced a reported failure: after a while the banner read "AI
 * service unavailable (401)" while the backend log said
 * `token rejected: Signature has expired`.
 *
 * It is not a one-off. `@convex-dev/auth`'s `fetchAccessToken` only refreshes
 * when it is asked to with `forceRefreshToken`, and the only thing that asks is
 * Convex's own client reacting to its own auth error. A hand-written fetch to a
 * different host is invisible to that, so `useAuthToken()` can hand back a token
 * that expired an hour ago and nothing ever corrects it.
 *
 * Routing through here removes the whole class of problem. `middleware.ts` wraps
 * `convexAuthNextjsMiddleware` and its matcher covers `/(api|trpc)(.*)`, so the
 * auth cookie is refreshed on the way in and `convexAuthNextjsToken()` below
 * reads a live one. The browser holds no token, so it cannot hold a stale one.
 *
 * It is also what the central API needs anyway: that one authenticates with an
 * application key, which must never reach the browser, and takes `user_id` as an
 * email, which must never be chosen by the browser. One door serves both.
 */

import { type NextRequest, NextResponse } from "next/server";

import {
  buildCentralRequest,
  centralConfig,
  centralConfigProblem,
  normalizeCentralResponse,
  type Principal,
} from "@/lib/consult/central";
// Helpers live outside this file: a route module may only export the handler
// names Next.js recognises, and exporting anything else fails the build.
import {
  callerToken,
  LOCAL_BACKEND,
  resolvePrincipal,
  sessionToken,
  usingCentral,
} from "@/lib/consult/server-session";

// Reads a cookie, so it must never be prerendered.
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const cookieToken = await sessionToken();
  const token = callerToken(request, cookieToken);
  if (!token) {
    // Kept deliberately. A 401 here is indistinguishable from several causes —
    // wrong cookie name, cookies cleared by the auth middleware, middleware not
    // running — and guessing between them cost a day. These are the facts that
    // separate them. NAMES only, never values: the token is a credential and
    // must not reach a log file.
    console.error(
      "[consult] no token from cookie OR header. " +
        `host=${request.headers.get("host")} ` +
        `origin=${request.headers.get("origin")} ` +
        `proto=${request.headers.get("x-forwarded-proto")} ` +
        `cookies=[${request.cookies.getAll().map((c) => c.name).join(", ")}]`,
    );
    // `signed_out`, not merely "unauthorised". Reaching here means BOTH auth
    // cookies are gone, and Convex Auth only removes both when a token refresh
    // has failed:
    //
    //     if (refreshToken === null || token === null) return null;  // -> cleared
    //
    // Reproduced exactly: an expired token plus a refresh token that cannot be
    // redeemed produces this response, an empty cookie jar, and no call to the
    // backend at all — which is why the reported failure left no trace in the
    // backend log.
    //
    // The session is genuinely over, so telling the reader to "refresh" is
    // wrong: a reload will bounce them to the login page anyway. Say what is
    // true and send them there in one step.
    return NextResponse.json(
      { error: "Your session has ended. Please sign in again.", reason: "signed_out" },
      { status: 401 },
    );
  }
  if (!cookieToken) {
    // Worth knowing about: it means the middleware is not handing this route a
    // refreshed cookie, so the fallback is carrying the session and a token can
    // still go stale the way it used to.
    console.warn("[consult] cookie token unavailable; using the Authorization header");
  }

  const incoming = (await request.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  if (!incoming) {
    return NextResponse.json({ error: "Malformed request." }, { status: 400 });
  }

  // ---- local: forward to the Python backend, unchanged ---------------------
  // Deliberately a pass-through. The backend already returns exactly the shape
  // the UI expects, so translating here would only add a place to get it wrong.
  if (!usingCentral) {
    try {
      const upstream = await fetch(`${LOCAL_BACKEND}/consult`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(incoming),
        signal: AbortSignal.timeout(180_000),
      });
      const text = await upstream.text();
      return new NextResponse(text, {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    } catch (error) {
      console.error("[consult] local backend unreachable:", error);
      return NextResponse.json(
        { error: "Could not reach the AI backend. Please try again." },
        { status: 502 },
      );
    }
  }

  // ---- central --------------------------------------------------------------
  const problem = centralConfigProblem();
  if (problem) {
    return NextResponse.json(
      { error: `The AI service is ${problem}.` },
      { status: 503 },
    );
  }

  let principal: Principal | null;
  try {
    principal = await resolvePrincipal(token);
  } catch (error) {
    console.error("[consult] could not resolve the session:", error);
    return NextResponse.json({ error: "Could not verify your session." }, { status: 500 });
  }
  if (!principal) {
    return NextResponse.json({ error: "Please sign in." }, { status: 401 });
  }

  const payload = buildCentralRequest({
    principal,
    message: (incoming.problem as string) ?? "",
    freeText: (incoming.freeText as string) ?? "",
    answers: (incoming.answers as Record<string, never>) ?? {},
    conversationId: (incoming.conversationId as string) ?? "",
    context: (incoming.context as never) ?? null,
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
    console.error(`[consult] central API ${upstream.status}: ${bodyText.slice(0, 500)}`);
    return NextResponse.json(
      { error: "The AI service returned an error. Please try again." },
      { status: 502 },
    );
  }

  try {
    return NextResponse.json(
      normalizeCentralResponse(
        JSON.parse(bodyText),
        (incoming.context as never) ?? null,
      ),
    );
  } catch (error) {
    console.error(
      `[consult] could not read the reply: ${(error as Error).message}\nraw: ${bodyText.slice(0, 800)}`,
    );
    return NextResponse.json(
      { error: "The AI service sent something this app could not read." },
      { status: 502 },
    );
  }
}
