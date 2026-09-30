"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { CircleCheck, CircleX, PencilLine, RotateCcw } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { z } from "zod";

import { InlineMarkdown } from "../message-content";
import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { parseJson } from "./tokens";

const Spec = z.object({ text: z.string().min(1).max(3000), explanation: z.string().max(2000).optional() });
type Part = string | { answers: string[] };

/** "Water boils at [[100|hundred]] °C" → text and blanks (each with its accepted answers). */
export function splitBlanks(text: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const match of text.matchAll(/\[\[([^\]\n]{1,80})\]\]/g)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    parts.push({ answers: (match[1] ?? "").split("|").map((answer) => answer.trim()).filter(Boolean) });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** Same answer, ignoring case, spacing and a trailing full stop. */
export function sameAnswer(given: string, expected: string): boolean {
  const norm = (value: string) => value.trim().toLowerCase().replace(/\s+/g, " ").replace(/[.;,!]+$/, "");
  return norm(given) === norm(expected);
}

/** ```fill-blank: a sentence with gaps to type into, checked with alternatives allowed. */
export default function FillBlank({ source, onError }: WidgetProps) {
  const spec = useMemo(() => {
    const parsed = Spec.safeParse(parseJson(source));
    if (!parsed.success) return null;
    const parts = splitBlanks(parsed.data.text);
    const blanks = parts.filter((part) => typeof part !== "string").length;
    return blanks > 0 && blanks <= 20 ? { ...parsed.data, parts } : null;
  }, [source]);
  const [given, setGiven] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (!spec) onError();
  }, [spec, onError]);
  if (!spec) return null;

  const blanks = spec.parts.filter((part): part is { answers: string[] } => typeof part !== "string");
  const right = blanks.map((blank, index) => blank.answers.some((answer) => sameAnswer(given[index] ?? "", answer)));
  const score = right.filter(Boolean).length;
  let blank = -1;

  return (
    <CardFrame kind="fill-blank" icon={PencilLine} label="Fill in the blanks">
      <p className="leading-9">
        {spec.parts.map((part, index) => {
          if (typeof part === "string") {
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: parts are positions in the sentence
              <Fragment key={index}>
                <InlineMarkdown text={part} />
              </Fragment>
            );
          }
          blank += 1;
          const which = blank;
          const width = Math.min(16, Math.max(4, ...part.answers.map((answer) => answer.length))) + 2;
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: parts are positions in the sentence
            <span key={index} className="mx-1 inline-flex max-w-full items-center gap-1 align-baseline">
              <input
                type="text"
                aria-label={`Blank ${which + 1}`}
                value={given[which] ?? ""}
                disabled={checked}
                onChange={(event) => setGiven((all) => Object.assign([...all], { [which]: event.target.value }))}
                style={{ width: `${width}ch` }}
                className={cn(
                  "max-w-full rounded-md border bg-card px-1.5 py-0.5 text-center text-sm leading-6 focus-ring",
                  checked ? (right[which] ? "border-success" : "border-destructive") : "border-input",
                )}
              />
              {checked &&
                (right[which] ? (
                  <CircleCheck aria-label="correct" className="h-4 w-4 shrink-0 text-success" />
                ) : (
                  <span className="inline-flex items-center gap-0.5 text-xs text-destructive">
                    <CircleX aria-hidden className="h-4 w-4 shrink-0" />
                    <span>{part.answers[0]}</span>
                  </span>
                ))}
            </span>
          );
        })}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {!checked ? (
          <Button type="button" size="sm" onClick={() => setChecked(true)} disabled={!given.some((value) => value?.trim())}>
            Check answers
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setGiven([]);
              setChecked(false);
            }}
          >
            <RotateCcw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
            Try again
          </Button>
        )}
        {checked && (
          <p role="status" className="text-sm font-semibold">
            {score} of {blanks.length} right
          </p>
        )}
      </div>
      {checked && spec.explanation ? (
        <p className="mt-2 text-sm leading-6">
          <InlineMarkdown text={spec.explanation} />
        </p>
      ) : null}
    </CardFrame>
  );
}
