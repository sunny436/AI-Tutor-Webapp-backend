/**
 * Attach a report: the browser's door to the backend's `/upload`.
 *
 * A sibling of `app/api/consult/route.ts`, for the same reason and with the same
 * shape. The browser used to post this directly to `AI_BACKEND_URL` carrying a
 * token it had no way to refresh — see `proxyMultipart` for why that is a bug
 * rather than a style preference.
 *
 * Uploads are authenticated deliberately. Without a verified user the backend
 * extracts the text but stores nothing, because there is no library to store it
 * in; a clear 401 here is more useful than a silent no-op there.
 */

import { type NextRequest, NextResponse } from "next/server";

import {
  callerToken,
  proxyMultipart,
  sessionToken,
} from "@/lib/consult/server-session";

// Reads a cookie, so it must never be prerendered.
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const token = callerToken(request, await sessionToken());
  if (!token) {
    return NextResponse.json(
      { error: "Please sign in to attach a report.", reason: "signed_out" },
      { status: 401 },
    );
  }

  try {
    return await proxyMultipart(request, "/upload", token);
  } catch (error) {
    console.error("[upload] backend unreachable:", error);
    return NextResponse.json(
      { error: "Could not reach the AI backend. Please try again." },
      { status: 502 },
    );
  }
}
