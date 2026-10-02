import "server-only";

import { headers } from "next/headers";
import { cache } from "react";

import type { Appearance, ConversationPage, StudyGreetingPool, User } from "@/lib/api/types";
import { type BackendResult, backendGet } from "./backend";
import { apiBaseUrl, authSecret } from "./config";
import { readSessionToken } from "./cookies";
import { publicProtocol } from "./public-origin";

/**
 * The session token from Better Auth's httpOnly cookie, for server components, once its signature
 * is verified. Same trust rule as the BFF: on HTTPS only the `__Host-` cookie counts.
 */
export const sessionToken = cache(async (): Promise<string | null> => {
  const requestHeaders = await headers();
  const https = publicProtocol(requestHeaders, "http://localhost/") === "https";
  return readSessionToken(requestHeaders.get("cookie"), https, authSecret());
});

/** Who is signed in (deduplicated per request). */
export const getCurrentUser = cache(
  async (): Promise<BackendResult<User>> => backendGet<User>(apiBaseUrl(), "/v1/me", await sessionToken()),
);

/** The first page of the sidebar, fetched alongside the user on a full page load. */
export const getInitialConversations = cache(
  async (): Promise<BackendResult<ConversationPage>> =>
    backendGet<ConversationPage>(apiBaseUrl(), "/v1/conversations?limit=30", await sessionToken()),
);

/**
 * This week's study greetings (app-level). Per request like everything here (React `cache` and a
 * `no-store` fetch), so they can never outlive their week; a short timeout, so a slow answer never
 * holds up the page: the empty chat then shows the fallback (lib/greeting.ts).
 */
export const getStudyGreetings = cache(
  async (): Promise<BackendResult<StudyGreetingPool>> =>
    backendGet<StudyGreetingPool>(apiBaseUrl(), "/v1/greetings", await sessionToken(), { timeoutMs: 1500 }),
);

/** How the app looks for this user; applied on the client (AppearanceProvider). */
export const getAppearance = cache(
  async (): Promise<BackendResult<Appearance>> =>
    backendGet<Appearance>(apiBaseUrl(), "/v1/me/appearance", await sessionToken()),
);
