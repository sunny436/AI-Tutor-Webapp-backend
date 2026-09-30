"use client";

import { Button } from "@v1/ui/button";
import { ChevronLeft, ChevronRight, Layers, RotateCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";

import { InlineMarkdown } from "../message-content";
import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { parseJson } from "./tokens";

const Deck = z.object({
  title: z.string().max(200).optional(),
  cards: z
    .array(z.object({ front: z.string().min(1).max(1000), back: z.string().min(1).max(2000) }))
    .min(1)
    .max(100),
});

/** ```flashcards: a deck to revise with. Tap (or Enter/Space) turns a card over. */
export default function Flashcards({ source, onError }: WidgetProps) {
  const deck = useMemo(() => {
    const parsed = Deck.safeParse(parseJson(source));
    return parsed.success ? parsed.data : null;
  }, [source]);
  const [at, setAt] = useState(0);
  const [back, setBack] = useState(false);
  useEffect(() => {
    if (!deck) onError();
  }, [deck, onError]);
  if (!deck) return null;

  const total = deck.cards.length;
  const card = deck.cards[Math.min(at, total - 1)];
  if (!card) return null;
  const go = (next: number) => {
    setAt(Math.min(total - 1, Math.max(0, next)));
    setBack(false);
  };

  return (
    <CardFrame kind="flashcards" icon={Layers} label="Flashcards" title={deck.title}>
      <button
        type="button"
        onClick={() => setBack((shown) => !shown)}
        aria-label={back ? "Card answer. Show the question" : "Card question. Show the answer"}
        className="focus-ring flex min-h-40 w-full flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card px-4 py-6 text-center transition-colors hover:border-brand/50"
      >
        <span className="text-2xs font-semibold uppercase tracking-wide text-text-secondary">{back ? "Answer" : "Question"}</span>
        <span aria-live="polite" className="max-w-full break-words text-base leading-7">
          <InlineMarkdown text={back ? card.back : card.front} />
        </span>
        <span className="inline-flex items-center gap-1 text-2xs text-text-secondary">
          <RotateCw aria-hidden className="h-3 w-3" />
          Tap to turn over
        </span>
      </button>
      <div className="mt-3 flex items-center justify-between gap-2 text-sm">
        <Button type="button" variant="outline" size="sm" onClick={() => go(at - 1)} disabled={at === 0}>
          <ChevronLeft aria-hidden className="mr-1 h-4 w-4" />
          Previous
        </Button>
        <span className="text-text-secondary">
          {at + 1} / {total}
        </span>
        <Button type="button" variant="outline" size="sm" onClick={() => go(at + 1)} disabled={at >= total - 1}>
          Next
          <ChevronRight aria-hidden className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </CardFrame>
  );
}
