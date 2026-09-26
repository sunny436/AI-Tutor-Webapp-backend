import { describe, expect, test } from "bun:test";

import { UNSAVED_MESSAGE, createNavigationGuard } from "./navigation-guard";

/** A browser history: pushState adds an entry, back/forward move and fire popstate later. */
function browser(start: string[], answer: boolean[] = []) {
  const entries = start.map((href) => ({ href, state: { __NA: true } as unknown }));
  let index = entries.length - 1;
  const queue: (() => void)[] = [];
  const asked: string[] = [];
  const guard = createNavigationGuard();
  const move = (delta: number) =>
    queue.push(() => {
      const next = index + delta;
      if (next < 0 || next >= entries.length) return;
      index = next;
      guard.popstate(entries[index]?.state);
    });
  guard.attach({
    confirm: (message) => {
      asked.push(message);
      return answer.shift() ?? false;
    },
    history: {
      get state() {
        return entries[index]?.state;
      },
      pushState: (data, _unused, url) => {
        entries.splice(index + 1);
        entries.push({ href: url ?? entries[index]?.href ?? "", state: { __NA: true, ...(data as object) } });
        index += 1;
      },
      back: () => move(-1),
      forward: () => move(1),
    },
    href: () => entries[index]?.href ?? "",
  });
  const settle = () => {
    for (let guardSteps = 0; queue.length && guardSteps < 20; guardSteps += 1) queue.shift()?.();
  };
  return {
    guard,
    asked,
    back: () => {
      move(-1);
      settle();
    },
    forward: () => {
      move(1);
      settle();
    },
    /** A normal navigation (a link): Next pushes the new page. */
    go: (href: string) => {
      entries.splice(index + 1);
      entries.push({ href, state: { __NA: true } });
      index += 1;
      guard.navigated(href);
    },
    get href() {
      return entries[index]?.href;
    },
    get length() {
      return entries.length;
    },
  };
}

describe("the unsaved-changes guard", () => {
  test("one question however many forms are dirty, and none once they are clean", () => {
    const b = browser(["/c/1", "/settings/profile"], [false, true]);
    const nameForm = {};
    const emailForm = {};
    b.guard.setDirty(nameForm, true);
    b.guard.setDirty(emailForm, true);
    expect(b.guard.confirmLeave()).toBe(false);
    expect(b.guard.confirmLeave()).toBe(true);
    expect(b.asked).toEqual([UNSAVED_MESSAGE, UNSAVED_MESSAGE]);
    b.guard.setDirty(nameForm, false);
    b.guard.setDirty(emailForm, false);
    expect(b.guard.isDirty()).toBe(false);
    expect(b.guard.confirmLeave()).toBe(true);
    expect(b.asked).toHaveLength(2);
  });

  test("the first edit adds one sentinel; more edits add none", () => {
    const b = browser(["/c/1", "/settings/profile"]);
    const form = {};
    b.guard.setDirty(form, true);
    b.guard.setDirty(form, false);
    b.guard.setDirty(form, true);
    expect(b.length).toBe(3);
    expect(b.href).toBe("/settings/profile");
  });

  test("Back with an edit, answered Stay: still on the page, still protected", () => {
    const b = browser(["/c/1", "/settings/profile"], [false, false]);
    b.guard.setDirty({}, true);
    b.back();
    expect(b.asked).toHaveLength(1);
    expect(b.href).toBe("/settings/profile");
    b.back(); // asked again
    expect(b.asked).toHaveLength(2);
    expect(b.href).toBe("/settings/profile");
  });

  test("Back with an edit, answered Leave: one question, then the previous page", () => {
    const b = browser(["/c/1", "/settings/profile"], [true]);
    b.guard.setDirty({}, true);
    b.back();
    expect(b.asked).toHaveLength(1);
    expect(b.href).toBe("/c/1");
    expect(b.guard.isDirty()).toBe(false); // leaving: the unload prompt won't ask again
  });

  test("Back after the edit was saved: straight to the previous page, no question", () => {
    const b = browser(["/c/1", "/settings/profile"]);
    const form = {};
    b.guard.setDirty(form, true);
    b.guard.setDirty(form, false);
    b.back();
    expect(b.asked).toHaveLength(0);
    expect(b.href).toBe("/c/1");
  });

  test("a sentinel left behind is stepped over in both directions", () => {
    const b = browser(["/c/1", "/settings/profile"], [true]);
    const form = {};
    b.guard.setDirty(form, true);
    expect(b.guard.confirmLeave()).toBe(true); // a link, answered Leave
    b.guard.setDirty(form, false); // the page unmounts
    b.go("/settings/notifications");
    expect(b.length).toBe(4); // /c/1, profile, sentinel, notifications
    b.back();
    expect(b.href).toBe("/settings/profile");
    b.forward(); // onto the sentinel from its own page: carry on forward
    expect(b.href).toBe("/settings/notifications");
    expect(b.asked).toHaveLength(1);
  });

  test("a new edit after leaving is protected again", () => {
    const b = browser(["/c/1", "/settings/profile"], [true, false]);
    const form = {};
    b.guard.setDirty(form, true);
    b.guard.confirmLeave();
    b.guard.setDirty(form, false);
    b.go("/settings/privacy");
    b.guard.setDirty({}, true);
    expect(b.guard.isDirty()).toBe(true);
    b.back();
    expect(b.asked).toHaveLength(2);
    expect(b.href).toBe("/settings/privacy");
  });

  test("without a browser (server render, or before the root mounts) it never blocks", () => {
    const guard = createNavigationGuard();
    guard.setDirty({}, true);
    expect(guard.confirmLeave()).toBe(true);
    guard.popstate({ padhaiGuard: 1 });
  });
});
