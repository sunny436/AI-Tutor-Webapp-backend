"use client";

import {
  Apple,
  ClipboardCheck,
  HeartPulse,
  Search,
  ShieldAlert,
  Sparkles,
  Sun,
  Wind,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Renders the assistant's plan.
 *
 * TWO THINGS CHANGED HERE.
 *
 * 1. COLOUR. This file used to carry a second, parallel design system: a
 *    `PALETTE` object of six hardcoded Tailwind hues (amber, emerald, sky, lime,
 *    violet, rose), selected by string-matching the section heading. Six
 *    competing colours on one answer is a rainbow, not a hierarchy — everything
 *    is emphasised so nothing is. The ICONS now carry the differentiation, which
 *    is what icons are for, and colour is spent in the two places it means
 *    something: saffron on Root Cause (the finding) and the destructive token on
 *    When To See A Doctor (the safety rail, and the one section the backend
 *    forces into every answer — `ALWAYS_INCLUDED` in sections.py).
 *
 * 2. MARKDOWN. The old renderer understood exactly two things: `**bold**` and a
 *    leading bullet character. Anything else the model emitted — numbered steps,
 *    nested bullets, inline code, a `## heading` inside a section — rendered as
 *    literal asterisks and hashes in the user's face. The prompts ask for
 *    structure, so the structure arrives; it just was not being read.
 *
 * Still deliberately NOT a markdown library. The input is not arbitrary
 * markdown: it is generated against `ANSWER_PROMPT` and reliably produces bold
 * headings, bullets and numbered steps. A parser for that is ~60 lines, and
 * pulling in react-markdown plus a sanitiser to cover syntax that never arrives
 * would add bundle weight and a new XSS surface for no gain.
 */

const SECTION_STYLES = {
  finding: {
    card: "border-accent-warm/25 bg-accent-warm-soft/50",
    title: "text-accent-warm",
    icon: "bg-accent-warm/15 text-accent-warm",
  },
  safety: {
    card: "border-destructive/25 bg-destructive/5",
    title: "text-destructive",
    icon: "bg-destructive/10 text-destructive",
  },
  standard: {
    card: "border-border bg-card",
    title: "text-foreground",
    icon: "bg-brand-soft text-brand",
  },
} as const;

function styleFor(title: string): { Icon: LucideIcon; tone: keyof typeof SECTION_STYLES } {
  const t = title.toLowerCase();
  if (t.includes("cause")) return { Icon: Search, tone: "finding" };
  if (
    t.includes("doctor") ||
    t.includes("serious") ||
    t.includes("emergency") ||
    t.includes("see a")
  )
    return { Icon: ShieldAlert, tone: "safety" };
  if (t.includes("food") || t.includes("diet") || t.includes("eat"))
    return { Icon: Apple, tone: "standard" };
  if (
    t.includes("yoga") ||
    t.includes("breath") ||
    t.includes("pranayam") ||
    t.includes("asana")
  )
    return { Icon: Wind, tone: "standard" };
  if (t.includes("routine") || t.includes("daily") || t.includes("dinacharya"))
    return { Icon: Sun, tone: "standard" };
  if (t.includes("remedy") || t.includes("remedies") || t.includes("home"))
    return { Icon: HeartPulse, tone: "standard" };
  if (
    t.includes("change") ||
    t.includes("do") ||
    t.includes("avoid") ||
    t.includes("lifestyle")
  )
    return { Icon: ClipboardCheck, tone: "standard" };
  return { Icon: Sparkles, tone: "standard" };
}

/**
 * Inline markup within one line: `**bold**`, `*italic*`, `` `code` ``.
 *
 * One pass over a single split, so the segments cannot overlap or nest
 * incorrectly. Index keys are safe here and only here: the array is a pure
 * function of an immutable string, nothing is reordered, and no child holds
 * state. Content-derived keys would collide on repeated words.
 */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|(?<![*\w])\*[^*\n]+\*(?!\w))/g).map((part, index) => {
    const key = `${index}-${part.slice(0, 12)}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={key} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={key} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return <span key={key}>{part}</span>;
  });
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "h"; text: string };

/**
 * Group consecutive lines into blocks, so a run of bullets becomes ONE list.
 *
 * The old renderer emitted a separate flex row per bullet, which meant no `<ul>`
 * and no `<li>` — a screen reader could not say "list, 6 items", and the reader
 * lost the one cue that tells them how much is coming.
 */
function toBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;

    const bullet = line.match(/^[-*•]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    const last = blocks[blocks.length - 1];

    if (heading?.[1]) {
      blocks.push({ kind: "h", text: heading[1] });
    } else if (bullet?.[1] !== undefined) {
      if (last?.kind === "ul") last.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
    } else if (numbered?.[1] !== undefined) {
      if (last?.kind === "ol") last.items.push(numbered[1]);
      else blocks.push({ kind: "ol", items: [numbered[1]] });
    } else if (last?.kind === "p") {
      last.lines.push(line);
    } else {
      blocks.push({ kind: "p", lines: [line] });
    }
  }
  return blocks;
}

function Body({ lines }: { lines: string[] }) {
  const blocks = toBlocks(lines);
  return (
    <div className="space-y-2">
      {blocks.map((block, index) => {
        const key = `${block.kind}-${index}`;
        if (block.kind === "h") {
          return (
            <h4 key={key} className="pt-1 text-sm font-semibold text-foreground">
              {inline(block.text)}
            </h4>
          );
        }
        if (block.kind === "ul") {
          return (
            <ul key={key} className="space-y-1.5">
              {block.items.map((item, i) => (
                <li
                  key={`${i}-${item.slice(0, 16)}`}
                  className="flex gap-2 text-sm leading-relaxed text-text-secondary"
                >
                  <span
                    aria-hidden
                    className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-current opacity-40"
                  />
                  <span className="min-w-0">{inline(item)}</span>
                </li>
              ))}
            </ul>
          );
        }
        if (block.kind === "ol") {
          return (
            <ol key={key} className="space-y-1.5">
              {block.items.map((item, i) => (
                <li
                  key={`${i}-${item.slice(0, 16)}`}
                  className="flex gap-2.5 text-sm leading-relaxed text-text-secondary"
                >
                  <span
                    aria-hidden
                    className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-surface-2 font-mono text-[10px] tabular-nums text-foreground"
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0">{inline(item)}</span>
                </li>
              ))}
            </ol>
          );
        }
        return (
          <p key={key} className="text-sm leading-relaxed text-text-secondary">
            {inline(block.lines.join(" "))}
          </p>
        );
      })}
    </div>
  );
}

function parseSections(text: string) {
  const out: { title: string | null; body: string[] }[] = [];
  let cur: { title: string | null; body: string[] } | null = null;
  for (const line of text.split("\n")) {
    // A whole line that is bold, or a markdown heading, opens a section.
    const bold = line.match(/^\s*\*\*(.+?)\*\*:?\s*$/);
    const hash = line.match(/^\s*#{1,3}\s+(.+?)\s*$/);
    const title = bold?.[1] ?? hash?.[1];
    if (title) {
      cur = { title, body: [] };
      out.push(cur);
    } else {
      if (!cur) {
        cur = { title: null, body: [] };
        out.push(cur);
      }
      cur.body.push(line);
    }
  }
  return out;
}

export function AnswerSections({ text }: { text: string }) {
  return (
    <div className="space-y-2.5">
      {parseSections(text).map((section, index) => {
        const key = `${index}-${section.title ?? "intro"}`;
        if (!section.title) {
          // Prose before the first heading — usually one framing sentence.
          if (section.body.every((line) => !line.trim())) return null;
          return <Body key={key} lines={section.body} />;
        }
        const { Icon, tone } = styleFor(section.title);
        const style = SECTION_STYLES[tone];
        return (
          <section key={key} className={`rounded-xl border p-3.5 ${style.card}`}>
            {/* A real heading. These were `div`s, so a plan was one flat blob to
                anyone navigating by heading — and the only way to reach "Food
                Chart" was to read everything above it. */}
            <h3 className={`mb-2 flex items-center gap-2 text-sm font-semibold ${style.title}`}>
              <span
                aria-hidden
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg ${style.icon}`}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              {section.title}
            </h3>
            <div className="pl-0.5">
              <Body lines={section.body} />
            </div>
          </section>
        );
      })}
    </div>
  );
}
