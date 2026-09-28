"use client";

import { useStudyGreeting } from "./chat-context";

/**
 * What a new, empty chat shows above the composer: this week's study greeting, the same for
 * everyone (lib/greeting.ts), and nothing else. It sits at the bottom of the transcript's space, so
 * it is directly above the composer, which the chat view centres while the chat is empty.
 */
export function ChatEmptyState() {
  const greeting = useStudyGreeting();
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 animate-rise-in flex-col justify-end px-4 pb-6 pt-10 sm:px-6">
      <h2 className="text-balance text-center font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
        {greeting}
      </h2>
    </div>
  );
}
