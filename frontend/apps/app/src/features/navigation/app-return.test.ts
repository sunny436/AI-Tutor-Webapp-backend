import { describe, expect, test } from "bun:test";

import { APP_RETURN_KEY, createAppReturn } from "./app-return";

function memory(initial?: string) {
  const values = new Map<string, string>(initial === undefined ? [] : [[APP_RETURN_KEY, initial]]);
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    values,
  };
}

describe("the page Close settings returns to", () => {
  test("is the last app page remembered, with its query", () => {
    const store = memory();
    const back = createAppReturn(() => store);
    back.remember("/c/7d9f5f2c-3f7e-4a57-9d0c-3b1f0b6f2a11");
    expect(back.get()).toBe("/c/7d9f5f2c-3f7e-4a57-9d0c-3b1f0b6f2a11");
    back.remember("/help?x=1#top");
    expect(back.get()).toBe("/help?x=1#top");
  });

  test("is home when nothing was remembered", () => {
    expect(createAppReturn(() => memory()).get()).toBe("/");
  });

  test("never becomes Settings, the unsubscribe page, the auth pages, the API or another site", () => {
    const store = memory();
    const back = createAppReturn(() => store);
    back.remember("/help");
    for (const bad of [
      "/settings",
      "/settings/privacy",
      "/c/../settings/profile",
      "/unsubscribe?token=x",
      "/login",
      "/api/v1/me",
      "//evil.example",
      "/\\evil.example",
      "https://evil.example/",
      "javascript:alert(1)",
      "help",
      "",
    ]) {
      back.remember(bad);
      expect(back.get()).toBe("/help");
    }
  });

  test("a stale or hand-edited stored value is read as home", () => {
    for (const stored of ["/settings/profile", "//evil.example", "%2F%2Fevil", "not a path", "/api/x"]) {
      expect(createAppReturn(() => memory(stored)).get()).toBe("/");
    }
  });

  test("follows a new chat to its address, and forgets a deleted one", () => {
    const store = memory();
    const back = createAppReturn(() => store);
    back.remember("/");
    back.retarget("/", "/c/abc");
    expect(back.get()).toBe("/c/abc");
    back.retarget("/", "/c/other"); // no longer "/": left alone
    expect(back.get()).toBe("/c/abc");
    back.forget("/c/other");
    expect(back.get()).toBe("/c/abc");
    back.forget("/c/abc");
    expect(back.get()).toBe("/");
  });

  test("tells its listeners when the page changes, so an open Close button follows", () => {
    const store = memory();
    let changes = 0;
    const back = createAppReturn(
      () => store,
      () => {
        changes += 1;
      },
    );
    back.remember("/");
    back.retarget("/", "/c/abc");
    back.remember("/settings/profile"); // refused: nothing written, nobody told
    expect(changes).toBe(2);
  });

  test("storage that is missing or throws means home, and never throws", () => {
    expect(createAppReturn(() => null).get()).toBe("/");
    const broken = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    };
    const back = createAppReturn(() => broken);
    expect(() => back.remember("/help")).not.toThrow();
    expect(() => back.retarget("/", "/c/x")).not.toThrow();
    expect(() => back.forget("/help")).not.toThrow();
    expect(back.get()).toBe("/");
  });
});
