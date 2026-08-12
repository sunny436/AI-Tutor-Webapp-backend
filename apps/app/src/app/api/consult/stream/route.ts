/**
 * The streaming sibling of `/api/consult`, for the same reason: so the browser
 * never has to hold a Convex token and therefore can never hold a stale one.
 *
 * The upstream body is handed straight back rather than read and re-emitted.
 * `new Response(upstream.body)` pipes it, so tokens still reach the reader as
 * they are written — buffering here would defeat the entire point of the
 * endpoint while looking like it worked.
 */

import { type NextRequest, NextResponse } from "next/server";

import { LOCAL_BACKEND, sessionToken, usingCentral } from "@/lib/consult/server-session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const token = await sessionToken();
  if (!token) {
    return NextResponse.json({ error: "Please sign in." }, { status: 401 });
  }

  // The central API is not known to stream yet. 501 rather than a silent
  // fallback: `postConsultStream` already falls back to `postConsult` on a
  // non-OK response, and the reply it produces is the authoritative one either
  // way, so the reader loses the typing effect and nothing else.
  if (usingCentral) {
    return NextResponse.json({ error: "Streaming not enabled." }, { status: 501 });
  }

  const body = await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${LOCAL_BACKEND}/consult/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body,
      signal: AbortSignal.timeout(180_000),
    });
  } catch (error) {
    console.error("[consult] local stream unreachable:", error);
    return NextResponse.json(
      { error: "Could not reach the AI backend." },
      { status: 502 },
    );
  }

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: `The AI backend returned an error (${upstream.status}).` },
      { status: upstream.status === 401 ? 401 : 502 },
    );
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      // Same header the Python backend sets. Any proxy in between will happily
      // buffer a response and deliver it in one piece otherwise.
      "X-Accel-Buffering": "no",
    },
  });
}
