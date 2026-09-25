"use client";

import { Button } from "@v1/ui/button";
import { useState } from "react";

import { FLASHCARDS } from "./demo-data";
import { ToolPage } from "./tool-page";

/**
 * Flashcards (preview): five sample cards. Flipping and moving between them
 * work here; saving progress and spacing reviews need the backend.
 */
export function FlashcardsView() {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = FLASHCARDS[index];
  if (!card) return null;

  const go = (step: number) => {
    setFlipped(false);
    setIndex((value) => (value + step + FLASHCARDS.length) % FLASHCARDS.length);
  };

  return (
    <ToolPage label="Flashcards" width="narrow" className="items-center">
      <div className="text-center">
        <span className="rounded-full bg-brand-soft px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand">
          Flashcard {index + 1} of {FLASHCARDS.length}
        </span>
        <h2 className="mt-3 text-xl font-bold text-foreground">Active Recall Practice</h2>
      </div>

      <button
        type="button"
        onClick={() => setFlipped((value) => !value)}
        aria-pressed={flipped}
        className="focus-ring bg-hero flex h-72 w-full max-w-2xl flex-col justify-between rounded-3xl p-6 text-left text-hero-foreground shadow-xl shadow-brand/20 transition-transform motion-safe:hover:scale-[1.01] motion-safe:active:scale-[0.99] sm:p-8"
      >
        <span className="flex items-center justify-between text-xs">
          <span className="rounded-full bg-hero-deep/35 px-3 py-1 font-semibold">{card.topic}</span>
          <span className="rounded-md bg-hero-foreground px-2 py-0.5 font-bold text-hero-deep">
            {card.level}
          </span>
        </span>
        <span aria-live="polite" className="my-auto block px-2 text-center">
          <span className="mb-2 block text-xs uppercase tracking-widest text-hero-muted">
            {flipped ? "Answer" : "Question"}
          </span>
          <span className={`block font-display font-bold leading-snug ${flipped ? "text-lg" : "text-xl"}`}>
            {flipped ? card.answer : card.question}
          </span>
        </span>
        <span className="block text-center text-2xs font-medium text-hero-muted">
          Tap card to {flipped ? "see question" : "flip answer"}
        </span>
      </button>

      <div className="flex items-center gap-4">
        <Button type="button" variant="outline" size="sm" onClick={() => go(-1)}>
          Previous
        </Button>
        <Button type="button" size="sm" onClick={() => go(1)}>
          Next Card
        </Button>
      </div>
    </ToolPage>
  );
}
