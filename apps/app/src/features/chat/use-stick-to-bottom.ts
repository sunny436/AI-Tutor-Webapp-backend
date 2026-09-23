"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

/** Within this many pixels of the bottom counts as "at the bottom". */
const NEAR_BOTTOM_PX = 80;

/**
 * Follow new content only while the reader is at the bottom.
 *
 * The old chat scrolled to the bottom on every token, yanking anyone who had
 * scrolled up to reread something. Here the scroller follows growth (a ResizeObserver
 * on the content) only while the reader is within ~80 px of the end; scrolling up
 * releases it, and `scrollToBottom()` (the "Jump to latest" button, or sending a
 * message) re-attaches it.
 */
export function useStickToBottom(
  scrollRef: RefObject<HTMLElement>,
  contentRef: RefObject<HTMLElement>,
  resetKey: string,
) {
  const stick = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      const element = scrollRef.current;
      if (!element) return;
      stick.current = true;
      setAtBottom(true);
      element.scrollTo({ top: element.scrollHeight, behavior });
    },
    [scrollRef],
  );

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const onScroll = () => {
      const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
      const near = distance <= NEAR_BOTTOM_PX;
      stick.current = near;
      setAtBottom(near);
    };
    element.addEventListener("scroll", onScroll, { passive: true });
    return () => element.removeEventListener("scroll", onScroll);
  }, [scrollRef]);

  useEffect(() => {
    const element = scrollRef.current;
    const content = contentRef.current;
    if (!element || !content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stick.current) element.scrollTop = element.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [scrollRef, contentRef]);

  // A different conversation opens at its latest message.
  useEffect(() => {
    scrollToBottom();
  }, [resetKey, scrollToBottom]);

  const release = useCallback(() => {
    stick.current = false;
  }, []);

  return { atBottom, scrollToBottom, release };
}
