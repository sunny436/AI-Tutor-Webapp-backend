"use client";

import { Download, FileText } from "lucide-react";
import { type ReactNode, Suspense, lazy, useCallback, useContext, useEffect, useState } from "react";

import { FileKindIcon } from "@/features/files/attachment-chip";
import { fileContentUrl, fileTypeOf } from "@/lib/api/files";
import { CitationsContext, LiveContext } from "./context";
import { CardFrame } from "./study-card";

const PdfPreview = lazy(() => import("./widgets/pdf-preview"));

const TEXT_PREVIEW_CHARS = 20_000;

/** A text file's bytes as the tutor read them: a BOM means UTF-16; otherwise UTF-8, else Windows-1252. */
export function decodeText(bytes: ArrayBuffer): string {
  const view = new Uint8Array(bytes);
  if (view[0] === 0xff && view[1] === 0xfe) return new TextDecoder("utf-16le").decode(view.subarray(2));
  if (view[0] === 0xfe && view[1] === 0xff) return new TextDecoder("utf-16be").decode(view.subarray(2));
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(view);
  } catch {
    return new TextDecoder("windows-1252").decode(view);
  }
}

function TextPreview({ url, onMissing }: { url: string; onMissing: () => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        const decoded = decodeText(await response.arrayBuffer());
        if (!cancelled) setText(decoded.length > TEXT_PREVIEW_CHARS ? `${decoded.slice(0, TEXT_PREVIEW_CHARS)}\n…` : decoded);
      })
      .catch(() => {
        if (!cancelled) onMissing();
      });
    return () => {
      cancelled = true;
    };
  }, [url, onMissing]);
  if (text === null) return <p className="text-sm text-text-secondary">Loading…</p>;
  return (
    <pre
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
      tabIndex={0}
      className="scrollbar-subtle focus-ring-inset max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-card p-3 font-mono text-xs leading-5"
    >
      {text}
    </pre>
  );
}

/**
 * `::file{ref=F1}` / `::pdf{ref=F1 page=3}`: a file the student attached to this chat, shown in
 * the reply. The ref is resolved through the reply's citations (the files numbered in its prompt),
 * so only the student's own files, fetched from this site, can ever appear.
 */
export function FileEmbed({ kind, fileRef, page }: { kind: "file" | "pdf"; fileRef: string; page?: number }) {
  const citations = useContext(CitationsContext);
  const live = useContext(LiveContext);
  const [missing, setMissing] = useState(false);
  const markMissing = useCallback(() => setMissing(true), []);
  const citation = citations?.find((item) => item.ref === fileRef && item.kind === "file");
  const fileId = citation?.fileId;

  if (live || citations === undefined || !fileId || missing) {
    const note = live || citations === undefined ? "Loading…" : "This file is no longer available in this chat.";
    return (
      <CardFrame kind="file" icon={FileText} label={`Attached file ${fileRef}`}>
        <p className="text-sm text-text-secondary">{note}</p>
      </CardFrame>
    );
  }

  const url = fileContentUrl(fileId);
  const type = fileTypeOf(citation.title)?.kind ?? null;
  const pdf = kind === "pdf" || type === "pdf";
  let preview: ReactNode;
  if (pdf) {
    preview = (
      <Suspense fallback={<p className="text-sm text-text-secondary">Loading…</p>}>
        <PdfPreview url={url} page={page ?? 1} onMissing={markMissing} />
      </Suspense>
    );
  } else if (type === "image") {
    preview = (
      <img
        src={url}
        alt={citation.title}
        loading="lazy"
        decoding="async"
        onError={markMissing}
        className="max-h-80 w-auto max-w-full rounded-lg border border-border bg-card"
      />
    );
  } else if (type === "txt" || type === "md" || type === "csv") {
    preview = <TextPreview url={url} onMissing={markMissing} />;
  } else {
    preview = <p className="text-sm text-text-secondary">No preview for this kind of file: download it to open it.</p>;
  }

  return (
    <CardFrame
      kind={pdf ? "pdf" : "file"}
      icon={FileText}
      label={`Your file ${fileRef}`}
      title={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FileKindIcon kind={type} className="h-3.5 w-3.5 shrink-0 text-text-secondary" />
          <span className="min-w-0 break-all">{citation.title}</span>
        </span>
      }
    >
      <div className="min-w-0">{preview}</div>
      <a
        href={url}
        download={citation.title}
        className="focus-ring mt-2 inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand"
      >
        <Download aria-hidden className="h-4 w-4" />
        Download
      </a>
    </CardFrame>
  );
}
