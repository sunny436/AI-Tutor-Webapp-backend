import { describe, expect, test } from "bun:test";

import { SETTINGS_SECTIONS, matchSections } from "./sections";

const slugs = (query: string) => matchSections(query).map((section) => section.slug);

describe("Settings search", () => {
  test("an empty or blank query lists every section, in order", () => {
    const all = SETTINGS_SECTIONS.map((section) => section.slug);
    expect(all).toHaveLength(13);
    expect(slugs("")).toEqual(all);
    expect(slugs("   ")).toEqual(all);
  });

  test("finds a section by what's in it, not only by its name", () => {
    expect(slugs("password")).toEqual(["privacy"]);
    expect(slugs("dark")).toEqual(["appearance"]);
    expect(slugs("hindi")).toEqual(["learning"]);
    expect(slugs("streak")).toContain("streak");
    expect(slugs("calendar")).toEqual(["streak"]);
    expect(slugs("delete account")).toEqual(["privacy"]);
  });

  test("partial words, any case, extra spaces", () => {
    expect(slugs("pass")).toEqual(["privacy"]);
    expect(slugs("PassWord")).toEqual(["privacy"]);
    expect(slugs("  NOTIF  ")).toEqual(["notifications"]);
  });

  test("every word must match", () => {
    expect(slugs("dark contrast")).toEqual(["appearance"]);
    expect(slugs("dark password")).toEqual([]);
  });

  test("nothing matches gibberish", () => {
    expect(slugs("zzzz")).toEqual([]);
  });

  test("every section is found by its own title", () => {
    for (const section of SETTINGS_SECTIONS) {
      expect(slugs(section.title)).toContain(section.slug);
    }
  });
});
