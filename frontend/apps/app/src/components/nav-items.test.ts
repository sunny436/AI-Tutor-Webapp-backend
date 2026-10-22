import { describe, expect, test } from "bun:test";
import { NAV_ITEMS, hubItems, isActive, navItemFor, visibleNavItems } from "./nav-items";

const tutor = NAV_ITEMS.find((item) => item.id === "tutor");
const homework = NAV_ITEMS.find((item) => item.id === "homework");

describe("nav items", () => {
  test("without preview features only the real tool is listed", () => {
    expect(visibleNavItems(false).map((item) => item.id)).toEqual(["tutor"]);
    expect(visibleNavItems(true).map((item) => item.id)).toEqual(["tutor", "homework", "summarizer"]);
  });

  test("the Learning Hub never lists the chat itself, and is empty without preview features", () => {
    expect(hubItems(false)).toEqual([]);
    expect(hubItems(true).map((item) => item.id)).toEqual(["homework", "summarizer"]);
  });

  test("the tutor owns / and every conversation, nothing else", () => {
    if (!tutor) throw new Error("no tutor item");
    expect(isActive(tutor, "/")).toBe(true);
    expect(isActive(tutor, "/c/11111111-1111-4111-8111-111111111111")).toBe(true);
    expect(isActive(tutor, "/settings")).toBe(false);
    expect(isActive(tutor, "/homework")).toBe(false);
    expect(isActive(tutor, null)).toBe(false);
  });

  test("a tool owns its path and below, not a longer name that shares a prefix", () => {
    if (!homework) throw new Error("no homework item");
    expect(isActive(homework, "/homework")).toBe(true);
    expect(isActive(homework, "/homework/science")).toBe(true);
    expect(isActive(homework, "/homework-archive")).toBe(false);
  });

  test("the page on screen maps to its tool", () => {
    expect(navItemFor("/")?.id).toBe("tutor");
    expect(navItemFor("/summarizer")?.id).toBe("summarizer");
    expect(navItemFor("/settings")).toBeNull();
    expect(navItemFor("/learning")).toBeNull(); // My Learning is a place of its own, not a tool
  });

  test("every href is unique and absolute", () => {
    const hrefs = NAV_ITEMS.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const href of hrefs) expect(href.startsWith("/")).toBe(true);
  });
});
