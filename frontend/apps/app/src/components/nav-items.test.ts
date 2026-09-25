import { describe, expect, test } from "bun:test";
import { NAV_ITEMS, isActive, navItemFor, visibleNavItems } from "./nav-items";

const tutor = NAV_ITEMS.find((item) => item.id === "tutor");
const courses = NAV_ITEMS.find((item) => item.id === "courses");

describe("nav items", () => {
  test("without preview features only the real tool is listed", () => {
    expect(visibleNavItems(false).map((item) => item.id)).toEqual(["tutor"]);
    expect(visibleNavItems(true).map((item) => item.id)).toEqual([
      "tutor",
      "courses",
      "homework",
      "summarizer",
      "course-creator",
      "flashcards",
    ]);
  });

  test("the tutor owns / and every conversation, nothing else", () => {
    if (!tutor) throw new Error("no tutor item");
    expect(isActive(tutor, "/")).toBe(true);
    expect(isActive(tutor, "/c/11111111-1111-4111-8111-111111111111")).toBe(true);
    expect(isActive(tutor, "/settings")).toBe(false);
    expect(isActive(tutor, "/courses")).toBe(false);
    expect(isActive(tutor, null)).toBe(false);
  });

  test("a tool owns its path and below, not a longer name that shares a prefix", () => {
    if (!courses) throw new Error("no courses item");
    expect(isActive(courses, "/courses")).toBe(true);
    expect(isActive(courses, "/courses/science")).toBe(true);
    expect(isActive(courses, "/courses-archive")).toBe(false);
  });

  test("the page on screen maps to its tool", () => {
    expect(navItemFor("/")?.id).toBe("tutor");
    expect(navItemFor("/flashcards")?.id).toBe("flashcards");
    expect(navItemFor("/settings")).toBeNull();
  });

  test("every href is unique and absolute", () => {
    const hrefs = NAV_ITEMS.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const href of hrefs) expect(href.startsWith("/")).toBe(true);
  });
});
