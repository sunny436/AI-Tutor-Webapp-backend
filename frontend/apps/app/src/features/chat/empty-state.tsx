"use client";

import { type CSSProperties, Fragment, useLayoutEffect, useRef, useState } from "react";

import { pickGreeting } from "@/lib/greeting";
import { useStudyGreetings } from "./chat-context";
import { StudyIllustration } from "./study-illustration";

/**
 * What a new, empty chat shows above the composer: a small, quiet picture (study-illustration.tsx)
 * and a study greeting picked at random from this week's pool, kept for this chat
 * (lib/greeting.ts), and nothing else. It sits at the bottom of the transcript's space, so it is
 * directly above the composer, which the chat view centres while the chat is empty.
 *
 * The words arrive one after another, each painted with its slice of ONE gradient that runs across
 * its line (measured, so the colour flows through the words instead of restarting in each). It is
 * one heading with the whole sentence, so a screen reader reads it once. Reduced motion (the
 * device's or the app's) shows the words at once (globals.css). It is one line on every screen: the
 * CSS size is the largest, and a sentence too wide for it is set smaller (fitOneLine).
 */
export function ChatEmptyState({ chatKey }: { chatKey: string }) {
  const pool = useStudyGreetings();
  // Picked on the client: the server cannot know the random pick, and a mismatch would flash.
  const [greeting, setGreeting] = useState<string | null>(null);
  useLayoutEffect(() => setGreeting(pickGreeting(chatKey, pool)), [chatKey, pool]);
  const ref = useLineGradient(greeting);

  // Wider than the chat column (57rem, message-list.tsx): at 57rem a long greeting is shrunk to one line
  // only when the web font arrives, and its height change moves the page (a layout shift).
  return (
    <div className="mx-auto flex w-full flex-1 flex-col justify-end px-5 pb-6 pt-10 sm:px-6 lg:w-[min(100%,clamp(42.5rem,75%,72rem))]">
      <StudyIllustration />
      <h2
        key={greeting ?? ""}
        ref={ref}
        data-greeting=""
        className="text-balance text-center font-display text-[length:clamp(1.5rem,1.05rem+2.2vw,2.25rem)] font-semibold leading-[1.2] tracking-tight text-foreground"
      >
        {greeting === null ? (
          <span className="invisible">&nbsp;</span>
        ) : (
          greeting.split(" ").map((word, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: the words of one fixed sentence, keyed with it
            <Fragment key={index}>
              {index > 0 && " "}
              <span data-greeting-word="" className="greeting-word" style={{ "--word": index } as CSSProperties}>
                {word}
              </span>
            </Fragment>
          ))
        )}
      </h2>
    </div>
  );
}

/** The smallest the greeting is set to stay on one line; a longer one wraps (balanced) at this size. */
const SMALLEST_PX = 12;

/** Shrinks the heading's font in proportion when the sentence is wider than the heading. */
function fitOneLine(heading: HTMLElement) {
  heading.style.fontSize = "";
  heading.style.whiteSpace = "nowrap";
  const natural = heading.scrollWidth;
  const room = heading.clientWidth;
  heading.style.whiteSpace = "";
  if (natural <= room) return;
  const size = Number.parseFloat(getComputedStyle(heading).fontSize);
  // 1% to spare, so rounding never pushes the last word onto a second line.
  heading.style.fontSize = `${Math.max(SMALLEST_PX, (size * room * 0.99) / natural)}px`;
}

/**
 * Fits the greeting on one line, then sizes each word's gradient to its whole line and offsets it
 * by the word's place in that line.
 */
function useLineGradient(greeting: string | null) {
  const ref = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    const heading = ref.current;
    if (!heading || greeting === null) return;
    const paint = () => {
      fitOneLine(heading);
      const lines = new Map<number, HTMLElement[]>();
      for (const word of heading.querySelectorAll<HTMLElement>("[data-greeting-word]")) {
        // Layout positions (offset*), which ignore the arrival transform.
        lines.set(word.offsetTop, [...(lines.get(word.offsetTop) ?? []), word]);
      }
      for (const words of lines.values()) {
        const first = words[0];
        const last = words[words.length - 1];
        if (!first || !last) continue;
        const width = last.offsetLeft + last.offsetWidth - first.offsetLeft;
        for (const word of words) {
          word.style.backgroundSize = `${width}px 100%`;
          word.style.backgroundPosition = `${first.offsetLeft - word.offsetLeft}px 0`;
        }
      }
    };
    paint();
    // Again whenever the line or a word changes size: the web font arriving moves the words
    // without resizing the heading.
    let mounted = true;
    const observer = new ResizeObserver(paint);
    observer.observe(heading);
    for (const word of heading.querySelectorAll("[data-greeting-word]")) observer.observe(word);
    void document.fonts?.ready.then(() => mounted && paint());
    return () => {
      mounted = false;
      observer.disconnect();
    };
  }, [greeting]);
  return ref;
}
