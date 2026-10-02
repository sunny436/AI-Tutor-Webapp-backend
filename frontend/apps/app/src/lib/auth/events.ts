/**
 * What Better Auth tells the API after it acts (backend/app/auth/internal.py): email a code, or
 * raise a security notice. The API keeps the one email sender and its templates, and it trusts
 * nothing here: it emails a code only when the code matches the hashed row Better Auth just
 * stored, and counts an event only when the rows it names exist and are fresh.
 *
 * Fire-and-forget: the caller never waits for the API or the mail provider (every answer takes
 * the same time whether or not an account exists), and a failure is logged without the address
 * or the code.
 */

export type AuthEvent =
  | { kind: "sign_in"; userId: string; sessionId: string }
  | { kind: "password_changed"; userId: string }
  | { kind: "password_reset"; userId: string }
  | { kind: "two_factor_on"; userId: string }
  | { kind: "two_factor_off"; userId: string }
  | { kind: "google_linked"; userId: string };

export type CodeMail = { email: string; type: "sign-in" | "forget-password"; otp: string };

export type InternalApi = { apiBaseUrl: string; token: string; fetchImpl?: typeof fetch };

const TIMEOUT_MS = 10_000;

export function postInternal(api: InternalApi, path: "code" | "events", body: AuthEvent | CodeMail): void {
  const call = (api.fetchImpl ?? fetch)(`${api.apiBaseUrl}/internal/auth/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Token": api.token },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
    cache: "no-store",
  });
  void call
    .then((response) => {
      if (response.status !== 202) console.error(`[auth] internal ${path} answered ${response.status}`);
    })
    .catch((error: unknown) => {
      console.error(`[auth] internal ${path} failed: ${error instanceof Error ? error.name : "error"}`);
    });
}
