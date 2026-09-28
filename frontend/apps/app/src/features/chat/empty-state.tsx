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
 * device's or the app's) shows the words at once (globals.css).
 */
export function ChatEmptyState({ chatKey }: { chatKey: string }) {
  const pool = useStudyGreetings();
  // Picked on the client: the server cannot know the random pick, and a mismatch would flash.
  const [greeting, setGreeting] = useState<string | null>(null);
  useLayoutEffect(() => setGreeting(pickGreeting(chatKey, pool)), [chatKey, pool]);
  const ref = useLineGradient(greeting);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-end px-4 pb-6 pt-10 sm:px-6">
      <StudyIllustration />
      <h2
        key={greeting ?? ""}
        ref={ref}
        data-greeting=""
        className="text-balance text-center font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
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

/** Sizes each word's gradient to its whole line and offsets it by the word's place in that line. */
function useLineGradient(greeting: string | null) {
  const ref = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    const heading = ref.current;
    if (!heading || greeting === null) return;
    const paint = () => {
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
