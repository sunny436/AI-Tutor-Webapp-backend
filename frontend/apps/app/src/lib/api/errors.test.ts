import { describe, expect, test } from "bun:test";
import { ApiError, describeCode, describeError, errorFromResponse } from "./errors";

const CONTRACT_CODES = [
  "unauthorized",
  "invalid_credentials",
  "email_not_verified",
  "invalid_code",
  "not_found",
  "conflict",
  "payload_too_large",
  "validation_error",
  "rate_limited",
  "service_unavailable",
  "internal_error",
  "llm_unavailable",
  "llm_timeout",
  "llm_bad_request",
  "storage_quota_exceeded",
  "unsupported_file_type",
  "file_too_large",
  "type_mismatch",
  "files_unavailable",
  "files_capacity_reached",
  "too_many_pending_files",
  "too_many_files",
  "retry_not_allowed",
  "busy",
];

describe("describeError", () => {
  test("every contract code has its own copy and an action", () => {
    for (const code of CONTRACT_CODES) {
      const description = describeError(new ApiError(400, code));
      expect(description.code).toBe(code as never);
      expect(description.title.length).toBeGreaterThan(0);
      expect(description.message.length).toBeGreaterThan(0);
    }
  });

  test("never echoes a backend message", async () => {
    const response = new Response(
      JSON.stringify({ error: { code: "internal_error", message: "Traceback: secret at db.py:42" } }),
      { status: 500 },
    );
    const description = describeError(await errorFromResponse(response));
    expect(`${description.title} ${description.message}`).not.toContain("Traceback");
  });

  test("unknown codes fall back on the HTTP status", () => {
    expect(describeError(new ApiError(429, "something_new")).code).toBe("rate_limited");
    expect(describeError(new ApiError(503, "")).code).toBe("service_unavailable");
    expect(describeError(new ApiError(418, "teapot")).code).toBe("unknown");
  });

  test("session expiry sends the user to sign in", () => {
    expect(describeError(new ApiError(401, "unauthorized")).action).toBe("sign_in");
  });

  test("a non-retryable failure does not offer retry", () => {
    expect(describeError(new ApiError(0, "internal_error", { retryable: false })).action).toBe("none");
  });

  test("a thrown TypeError reads as offline", () => {
    expect(describeError(new TypeError("Failed to fetch")).code).toBe("network_error");
  });

  test("the request id is kept for support", async () => {
    const response = new Response(JSON.stringify({ error: { code: "internal_error", requestId: "abc123" } }), {
      status: 500,
    });
    expect(describeError(await errorFromResponse(response)).requestId).toBe("abc123");
  });

  test("a non-JSON error body still produces a usable error", async () => {
    const error = await errorFromResponse(new Response("<html>Bad Gateway</html>", { status: 502 }));
    expect(error.code).toBe("service_unavailable");
  });
});

describe("describeCode (persisted message errors)", () => {
  test("maps metadata.errorCode, including a swept `interrupted` reply", () => {
    expect(describeCode("llm_timeout").code).toBe("llm_timeout");
    expect(describeCode("interrupted").code).toBe("interrupted");
    expect(describeCode(undefined).code).toBe("internal_error");
  });
});
