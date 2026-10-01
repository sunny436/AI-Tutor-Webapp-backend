import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/**
 * Colour comes from the design tokens (packages/ui/src/globals.css), never from literals in the
 * app: a raw hex, rgb() or hsl() in a component is a colour the themes, high contrast and the next
 * palette change cannot reach. Four places are allowed, each for a reason no token can serve.
 */
const SRC = join(import.meta.dir, "..");
const ALLOWED: Record<string, string> = {
  "app/global-error.tsx": "renders when the app itself has failed, so it carries its own tiny palette",
  "app/layout.tsx": "the browser's theme-color meta takes a literal colour",
  "components/google-mark.tsx": "Google's sign-in mark must keep Google's own colours (its branding guidelines)",
  "features/streak/LearningActivityCalendar.tsx": "the calendar draws on a canvas: fallbacks until the tokens are read",
};
const RAW_COLOUR = /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?\b|rgba?\(|hsla?\((?!var\(|\$\{)/;
const ARBITRARY_COLOUR = /\b(?:bg|text|border|ring|shadow|fill|stroke|from|via|to|outline|decoration|divide|caret|placeholder)-\[(?:#|rgb|hsl)/;
// The retired indigo/violet palette, which must not come back anywhere.
const LEGACY = /#(?:4F46E5|7C3AED|818CF8|6366F1|8B5CF6|A78BFA)\b/i;

function files(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("design tokens", () => {
  test("no raw colour in the app's code outside the documented exceptions", () => {
    const offenders = files(SRC)
      .map((path) => ({ path: relative(SRC, path).replaceAll("\\", "/"), lines: readFileSync(path, "utf-8").split("\n") }))
      .filter(({ path }) => !(path in ALLOWED))
      .flatMap(({ path, lines }) =>
        lines.flatMap((line, index) =>
          RAW_COLOUR.test(line) || ARBITRARY_COLOUR.test(line) ? [`${path}:${index + 1}: ${line.trim()}`] : [],
        ),
      );
    expect(offenders).toEqual([]);
  });

  test("the retired indigo/violet palette is gone from the app, the design system and the logo", () => {
    const roots = [SRC, join(SRC, "..", "public"), join(SRC, "..", "..", "..", "packages", "ui", "src")];
    const everywhere = roots.flatMap((root) =>
      readdirSync(root, { recursive: true })
        .map((name) => join(root, String(name)))
        .filter((path) => statSync(path).isFile() && /\.(tsx?|css|svg)$/.test(path) && !/\.test\.tsx?$/.test(path)),
    );
    const found = everywhere.filter((path) => LEGACY.test(readFileSync(path, "utf-8")));
    expect(found).toEqual([]);
  });
});
