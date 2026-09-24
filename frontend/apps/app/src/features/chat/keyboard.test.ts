import { describe, expect, test } from "bun:test";
import { shouldSubmit } from "./keyboard";
import { plainText } from "./plain-text";

describe("shouldSubmit", () => {
  test("Enter sends", () => {
    expect(shouldSubmit({ key: "Enter", shiftKey: false })).toBe(true);
  });

  test("Shift+Enter is a new line", () => {
    expect(shouldSubmit({ key: "Enter", shiftKey: true })).toBe(false);
  });

  test("Enter confirming an IME composition does not send", () => {
    expect(shouldSubmit({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: true } })).toBe(false);
    expect(shouldSubmit({ key: "Enter", shiftKey: false, isComposing: true })).toBe(false);
    // Safari reports composition only through the legacy keyCode.
    expect(shouldSubmit({ key: "Enter", shiftKey: false, keyCode: 229 })).toBe(false);
  });

  test("other keys never send", () => {
    expect(shouldSubmit({ key: "a", shiftKey: false })).toBe(false);
  });
});

describe("plainText (screen-reader announcement)", () => {
  test("strips Markdown syntax", () => {
    expect(plainText("# Title\n\n**Bold** and `code` with a [link](https://x.y).\n\n- item")).toBe(
      "Title Bold and code with a link. item",
    );
  });

  test("summarises code blocks instead of reading them", () => {
    expect(plainText("Here:\n```js\nconst x = 1;\n```\nDone.")).toBe("Here: (code) Done.");
  });

  test("caps the length", () => {
    expect(plainText("word ".repeat(500), 20)).toBe("word word word word…");
  });
});
