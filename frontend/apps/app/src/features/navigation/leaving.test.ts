import { describe, expect, test } from "bun:test";

import { createLeavingTracker } from "./leaving";

const HERE = new URL("https://padhai.test/");

type Init = Partial<{ button: number; meta: boolean; ctrl: boolean; shift: boolean; alt: boolean; target: string; download: boolean }>;

/** A click on a link, as the listener receives it (no DOM needed). */
function click(href: string | null, init: Init = {}) {
  const anchor =
    href === null
      ? null
      : {
          href: new URL(href, HERE).href,
          target: init.target ?? "",
          hasAttribute: (name: string) => name === "download" && Boolean(init.download),
        };
  return {
    button: init.button ?? 0,
    metaKey: Boolean(init.meta),
    ctrlKey: Boolean(init.ctrl),
    shiftKey: Boolean(init.shift),
    altKey: Boolean(init.alt),
    target: { closest: () => anchor } as unknown as EventTarget,
  };
}

describe("leaving: where a navigation in flight is heading", () => {
  test("a link to another page of the app", () => {
    const tracker = createLeavingTracker();
    tracker.click(click("/settings/profile"), HERE);
    expect(tracker.current()).toBe("/settings/profile");
  });

  test("the latest click wins: a link back to this page means staying", () => {
    const tracker = createLeavingTracker();
    tracker.click(click("/settings/profile"), HERE);
    tracker.click(click("/"), HERE);
    expect(tracker.current()).toBeNull();
  });

  test("never set by clicks that do not navigate this tab", () => {
    const tracker = createLeavingTracker();
    tracker.click(click("/settings", { meta: true }), HERE);
    tracker.click(click("/settings", { ctrl: true }), HERE);
    tracker.click(click("/settings", { shift: true }), HERE);
    tracker.click(click("/settings", { alt: true }), HERE);
    tracker.click(click("/settings", { button: 1 }), HERE);
    tracker.click(click("/settings", { target: "_blank" }), HERE);
    tracker.click(click("/export.pdf", { download: true }), HERE);
    tracker.click(click("https://elsewhere.test/settings"), HERE);
    tracker.click(click(null), HERE); // not a link
    expect(tracker.current()).toBeNull();
  });

  test("cleared when the navigation commits or history moves: it can never go stale", () => {
    const tracker = createLeavingTracker();
    tracker.click(click("/settings/profile"), HERE);
    tracker.settled();
    expect(tracker.current()).toBeNull();
  });

  test("only observes: it never cancels or redirects the click", () => {
    const tracker = createLeavingTracker();
    let prevented = false;
    const event = {
      ...click("/settings/profile"),
      preventDefault: () => {
        prevented = true;
      },
    };
    tracker.click(event, HERE);
    expect(prevented).toBe(false);
  });
});
