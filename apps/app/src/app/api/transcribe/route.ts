/**
 * Voice input: the browser's door to the backend's `/transcribe`.
 *
 * Sibling of `app/api/upload/route.ts`; see `proxyMultipart` for why neither of
 * these calls the backend directly any more.
 *
 * The clip's extension matters and is set by the caller — MediaRecorder produces
 * webm on Chrome and mp4 on Safari, and the backend passes the mime straight to
 * the model. Forwarding the body as raw bytes keeps that intact.
 */

import { type NextRequest, NextResponse } from "next/server";

import {
  callerToken,
  proxyMultipart,
  sessionToken,
} from "@/lib/consult/server-session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const token = callerToken(request, await sessionToken());
  if (!token) {
    return NextResponse.json(
      { error: "Please sign in to use voice input.", reason: "signed_out" },
      { status: 401 },
    );
  }

  try {
    return await proxyMultipart(request, "/transcribe", token);
  } catch (error) {
    console.error("[transcribe] backend unreachable:", error);
    return NextResponse.json(
      { error: "Could not reach the AI backend. Please try again." },
      { status: 502 },
    );
  }
}
