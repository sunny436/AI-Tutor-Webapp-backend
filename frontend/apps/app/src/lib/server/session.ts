import "server-only";

import { cookies, headers } from "next/headers";
import { cache } from "react";

import type { ConversationPage, User } from "@/lib/api/types";
import { type BackendResult, backendGet } from "./backend";
import { apiBaseUrl } from "./config";
import { PLAIN_COOKIE, SECURE_COOKIE } from "./cookies";
import { publicProtocol } from "./public-origin";

/**
 * The session token from the httpOnly cookie, for server components.
 * Same trust rule as the BFF: on HTTPS only the `__Host-` cookie counts.
 */
export function sessionToken(): string | null {
  const store = cookies();
  const requestHeaders = headers();
  const https = publicProtocol(requestHeaders, "http://localhost/") === "https";
  const value = https
    ? store.get(SECURE_COOKIE)?.value
    : (store.get(PLAIN_COOKIE)?.value ?? store.get(SECURE_COOKIE)?.value);
  if (!value) return null;
  try {
    return decodeURIComponent(value) || null;
  } catch {
    return null;
  }
}

/** Who is signed in (deduplicated per request). */
export const getCurrentUser = cache(
  (): Promise<BackendResult<User>> => backendGet<User>(apiBaseUrl(), "/v1/me", sessionToken()),
);

/** The first page of the sidebar, fetched alongside the user on a full page load. */
export const getInitialConversations = cache(
  (): Promise<BackendResult<ConversationPage>> =>
    backendGet<ConversationPage>(apiBaseUrl(), "/v1/conversations?limit=30", sessionToken()),
);
