"use client";

import { Badge } from "@v1/ui/badge";
import { BookOpen, ChevronDown, FileText, History, Library } from "lucide-react";
import { useId, useState } from "react";
import type { ConsultSource } from "@/lib/consult/types";

/**
 * Where this answer came from.
 *
 * THE POINT OF THE WHOLE FEATURE
 *
 * The backend has always returned this. `retrieval/pipeline.py:88` builds it and
 * its docstring reads "Compact provenance list, safe to return to the client";
 * `graph.py:333` attaches it to knowledge answers and `graph.py:581` to the
 * final plan. And there was not one render site in the entire app — a grep for
 * `sources` across `apps/app/src` returned the type definition, the central-API
 * normaliser, and nothing else.
 *
 * So the single thing separating this product from a chatbot with a good prompt
 * — that every plan is retrieved from curated notes rather than recalled from
 * the model's training — was invisible to the person reading the answer.
 *
 * WHY THE KINDS ARE KEPT APART
 *
 * `Chunk.source` is namespaced (see `retrieval/base.py:60`), and the namespaces
 * mean genuinely different things:
 *
 *   knowledge:acidity.md    the shared, curated Ayurveda corpus
 *   report:bloodwork.pdf    a document THIS user uploaded
 *   memory:<sessionId>      something they said in an earlier consultation
 *
 * Flattening those into one count would be a false claim: "based on 3 Ayurveda
 * notes" is untrue if one of them is the reader's own blood test, and citing
 * their own past message back at them as a source is circular. They are grouped,
 * labelled for what they are, and memory is shown last and unscored — it is
 * context, not evidence.
 *
 * Deduplicated by file, because retrieval returns one entry per CHUNK. Measured
 * on a live answer: 4 entries, 1 actual note. Listing it four times would
 * overstate the evidence fourfold.
 */

const KINDS = {
  knowledge: {
    icon: BookOpen,
    one: "note from the Ayurveda knowledge base",
    many: "notes from the Ayurveda knowledge base",
    variant: "source" as const,
  },
  report: {
    icon: FileText,
    one: "document you uploaded",
    many: "documents you uploaded",
    variant: "info" as const,
  },
  // External document service. Named "reference document" rather than anything
  // mentioning GraphRAG: the reader does not know or care which vendor indexed
  // it, only that it is a supporting document rather than one of the curated
  // Ayurveda notes. Kept apart from `knowledge` for the same reason the others
  // are — counting it as an Ayurveda note would be a false claim.
  graphrag: {
    icon: Library,
    one: "reference document",
    many: "reference documents",
    variant: "neutral" as const,
  },
  memory: {
    icon: History,
    one: "earlier consultation",
    many: "earlier consultations",
    variant: "neutral" as const,
  },
};

type Kind = keyof typeof KINDS;
// Curated notes first, then the reader's own documents, then external reference
// material, and memory last — the same descending order of authority the prompt
// rules give them.
const ORDER: Kind[] = ["knowledge", "report", "graphrag", "memory"];

function classify(raw: string): { kind: Kind; name: string } {
  const at = raw.indexOf(":");
  const prefix = at === -1 ? "" : raw.slice(0, at);
  const rest = at === -1 ? raw : raw.slice(at + 1);
  if (prefix === "report") return { kind: "report", name: rest };
  if (prefix === "graphrag") return { kind: "graphrag", name: rest };
  if (prefix === "memory" || prefix === "convex") return { kind: "memory", name: rest };
  return { kind: "knowledge", name: rest };
}

// `.md` is how the corpus is stored, not what the topic is called. "acidity.md"
// is a file path leaking into a health product; "acidity" is the subject.
const pretty = (name: string) =>
  name
    .replace(/\.(mdx?|txt|pdf|docx?)$/i, "")
    .replace(/[-_]/g, " ")
    .trim();

export function AnswerSources({ sources }: { sources: ConsultSource[] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  if (!sources?.length) return null;

  const groups = new Map<Kind, Map<string, number | null>>();
  for (const entry of sources) {
    if (!entry?.source) continue;
    const { kind, name } = classify(entry.source);
    if (!name) continue;
    const bucket = groups.get(kind) ?? new Map<string, number | null>();
    const previous = bucket.get(name);
    const score = entry.score ?? null;
    // Keep the BEST score per file — the one that actually justified including it.
    if (previous === undefined || (score !== null && (previous === null || score > previous))) {
      bucket.set(name, score);
    }
    groups.set(kind, bucket);
  }

  const present = ORDER.filter((kind) => (groups.get(kind)?.size ?? 0) > 0);
  if (present.length === 0) return null;

  // The summary names only the largest group, so the closed state stays one
  // short line; the rest is a count. Expanding shows every group properly.
  const primary = present[0] as Kind;
  const primaryCount = groups.get(primary)?.size ?? 0;
  const others = present
    .slice(1)
    .reduce((total, kind) => total + (groups.get(kind)?.size ?? 0), 0);
  const PrimaryIcon = KINDS[primary].icon;

  return (
    <div className="mt-3 border-t border-border pt-2.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-2 text-left text-xs text-text-secondary transition-colors hover:text-foreground"
      >
        <PrimaryIcon aria-hidden className="h-3.5 w-3.5 shrink-0 text-accent-warm" />
        <span>
          Based on{" "}
          <span className="font-medium text-foreground">
            {primaryCount}{" "}
            {primaryCount === 1 ? KINDS[primary].one : KINDS[primary].many}
          </span>
          {others > 0 && ` · +${others} more`}
        </span>
        <ChevronDown
          aria-hidden
          className={`ml-auto h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div id={panelId} className="mt-2.5 space-y-2">
          {present.map((kind) => {
            const files = [...(groups.get(kind) ?? new Map())].sort(
              (a, b) => (b[1] ?? 0) - (a[1] ?? 0),
            );
            return (
              <div key={kind}>
                <p className="mb-1 text-2xs uppercase tracking-wider text-text-secondary">
                  {files.length === 1 ? KINDS[kind].one : KINDS[kind].many}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {files.map(([name, score]) => (
                    <Badge key={name} variant={KINDS[kind].variant} title={name}>
                      {pretty(name)}
                      {typeof score === "number" && (
                        // One decimal. The embedding is not precise enough to
                        // justify two, and a longer number reads as a
                        // measurement rather than a hint.
                        <span className="opacity-60">{score.toFixed(1)}</span>
                      )}
                    </Badge>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
