"use client";

import { cn } from "@v1/ui/utils";
import { FileSpreadsheet, FileText, Image as ImageIcon, Loader2, Presentation, RotateCcw, X } from "lucide-react";

import { describeCode } from "@/lib/api/errors";
import { describeFileFailure } from "@/lib/api/files";
import type { FileKind } from "@/lib/api/types";
import type { Chip } from "./attachment-store";

export function FileKindIcon({ kind, className }: { kind: FileKind | null; className?: string }) {
  const Icon = kind === "image" ? ImageIcon : kind === "xlsx" || kind === "csv" ? FileSpreadsheet : kind === "pptx" ? Presentation : FileText;
  return <Icon aria-hidden className={className} />;
}

function status(chip: Chip): { text: string; tone: "muted" | "ok" | "bad"; detail?: string } {
  switch (chip.state) {
    case "hashing":
      return { text: "Preparing…", tone: "muted" };
    case "uploading":
      return { text: "Uploading", tone: "muted" };
    case "processing":
      return { text: "Reading…", tone: "muted" };
    case "ready":
      return { text: "Ready", tone: "ok" };
    case "stored":
      return { text: "Can't be read right now", tone: "bad", detail: "Files can't be read right now. Try again later." };
    case "missing":
      return { text: "No longer in your library", tone: "bad", detail: "This file was deleted. Remove it." };
    case "failed":
      return { text: "Failed", tone: "bad", detail: describeFileFailure(chip.errorCode) };
    case "upload_failed": {
      const described = describeCode(chip.errorCode ?? undefined);
      return { text: "Upload failed", tone: "bad", detail: `${described.title}. ${described.message}` };
    }
  }
}

/** A file on an unsent message: its name, where it is on the way to "ready", Retry and Remove. */
export function AttachmentChip({
  chip,
  onRemove,
  onRetry,
}: {
  chip: Chip;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const { text, tone, detail } = status(chip);
  const busy = chip.state === "hashing" || chip.state === "uploading" || chip.state === "processing";
  const canRetry = chip.state === "upload_failed" || (chip.state === "failed" && chip.retryable);
  return (
    <div
      className={cn(
        "flex max-w-[16rem] shrink-0 items-center gap-2 rounded-xl border bg-surface-2 py-1.5 pl-2 pr-1 text-left",
        tone === "bad" ? "border-destructive/40" : "border-border",
      )}
      title={detail ?? chip.name}
    >
      <FileKindIcon kind={chip.kind} className="h-4 w-4 shrink-0 text-text-secondary" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-foreground">{chip.name}</p>
        <p
          role="status"
          className={cn(
            "flex items-center gap-1 text-2xs",
            tone === "ok" && "text-success",
            tone === "bad" && "text-destructive",
            tone === "muted" && "text-text-secondary",
          )}
        >
          {busy && <Loader2 aria-hidden className="h-3 w-3 motion-safe:animate-spin" />}
          <span className="truncate">{text}</span>
          {chip.state === "uploading" && <span aria-hidden>{Math.round(chip.progress * 100)}%</span>}
          {detail && <span className="sr-only">. {detail}</span>}
        </p>
      </div>
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          aria-label={`Retry ${chip.name}`}
          className="focus-ring grid h-7 w-7 shrink-0 place-items-center rounded-lg text-text-secondary hover:bg-card hover:text-foreground"
        >
          <RotateCcw aria-hidden className="h-3.5 w-3.5" />
        </button>
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${chip.name}`}
        className="focus-ring grid h-7 w-7 shrink-0 place-items-center rounded-lg text-text-secondary hover:bg-card hover:text-foreground"
      >
        <X aria-hidden className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
