import { createHash } from "node:crypto";
import { describe, expect, test } from "bun:test";

import { passwordBreached, turnstileOk } from "./protection";

const sha1 = (value: string) => createHash("sha1").update(value).digest("hex").toUpperCase();

function fakeFetch(answer: (url: string, init?: RequestInit) => Response) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const impl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return answer(String(input), init);
  }) as typeof fetch;
  return { impl, calls };
}

describe("passwordBreached", () => {
  test("sends only the first five hex digits of the SHA-1, padded, and matches the suffix", async () => {
    const hash = sha1("password123");
    const { impl, calls } = fakeFetch(
      () => new Response(`0000000000000000000000000000000000A:0\r\n${hash.slice(5)}:2413945\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0`),
    );
    expect(await passwordBreached("password123", impl)).toBe(true);
    expect(calls[0]?.url).toBe(`https://api.pwnedpasswords.com/range/${hash.slice(0, 5)}`);
    expect(calls[0]?.url).not.toContain(hash.slice(5));
    expect(new Headers(calls[0]?.init?.headers).get("Add-Padding")).toBe("true");
  });

  test("a suffix that is only padding (count 0), or absent, is not a breach", async () => {
    const hash = sha1("a long and unusual passphrase 7781");
    const { impl } = fakeFetch(() => new Response(`${hash.slice(5)}:0\nABCDEF:3`));
    expect(await passwordBreached("a long and unusual passphrase 7781", impl)).toBe(false);
    const { impl: none } = fakeFetch(() => new Response("ABCDEF:3"));
    expect(await passwordBreached("a long and unusual passphrase 7781", none)).toBe(false);
  });

  test("an unavailable service throws (the caller refuses the password)", async () => {
    const { impl } = fakeFetch(() => new Response("", { status: 503 }));
    await expect(passwordBreached("whatever-123", impl)).rejects.toThrow();
  });
});

describe("turnstileOk", () => {
  test("posts the secret, the token and the client IP; only success: true passes", async () => {
    const { impl, calls } = fakeFetch(() => Response.json({ success: true }));
    expect(await turnstileOk("token-1", "secret-1", "203.0.113.9", impl)).toBe(true);
    const sent = new URLSearchParams(String(calls[0]?.init?.body));
    expect(calls[0]?.url).toBe("https://challenges.cloudflare.com/turnstile/v0/siteverify");
    expect([sent.get("secret"), sent.get("response"), sent.get("remoteip")]).toEqual(["secret-1", "token-1", "203.0.113.9"]);

    const { impl: refused } = fakeFetch(() => Response.json({ success: false, "error-codes": ["invalid-input-response"] }));
    expect(await turnstileOk("token-2", "secret-1", null, refused)).toBe(false);
  });

  test("no token is refused without asking; an unreachable Cloudflare throws", async () => {
    const { impl, calls } = fakeFetch(() => Response.json({ success: true }));
    expect(await turnstileOk("", "secret-1", null, impl)).toBe(false);
    expect(calls).toHaveLength(0);
    const { impl: down } = fakeFetch(() => new Response("", { status: 500 }));
    await expect(turnstileOk("token-3", "secret-1", null, down)).rejects.toThrow();
  });
});
