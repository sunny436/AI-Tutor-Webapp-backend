"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@v1/ui/dialog";
import { cn } from "@v1/ui/utils";
import { Timer } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { formatStudyTime, isLearningView } from "./study-client";
import { STATUS_LABELS, StudySessionPanel, type TabStatus, tabStatus } from "./study-session-panel";
import { studyStore, type StudySnapshot, useStudy } from "./study-store";

const pill =
  "focus-ring inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-sm font-semibold tabular-nums text-foreground hover:bg-surface-2 sm:px-3";

const DOTS: Record<TabStatus, string> = {
  studying: "bg-success",
  idle: "bg-warning",
  prompting: "bg-warning",
  paused: "bg-text-secondary",
  elsewhere: "border border-text-secondary",
  offline: "border border-text-secondary",
};

/** One source of truth for whether the header capsule needs the Study segment. */
export function studyControlVisible(study: StudySnapshot, pathname: string | null): boolean {
  return Boolean(study.server) && (study.server?.session !== null || isLearningView(pathname));
}

/**
 * The header's study status: Studying, Idle, Paused, "Not counted on this page" or Offline, and the
 * session's estimated study time as the server last counted it (it moves with each beat, every
 * 30 s; nothing here counts by itself). Opens the session's controls. On a page that is not a
 * learning view, shown only while a session is open; it never covers the page.
 */
export function StudyControl() {
  const study = useStudy();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const session = study.server?.session ?? null;
  const status = tabStatus(study, pathname);
  if (!studyControlVisible(study, pathname)) return null;

  const label = session
    ? `${STATUS_LABELS[status ?? "studying"]}: ${formatStudyTime(session.activeSeconds)} of estimated study time. Study session controls`
    : "Start a study session";

  return (
    <>
      <span className="sr-only" aria-live="polite">
        {status ? STATUS_LABELS[status] : ""}
      </span>
      {status === "prompting" && (
        <button type="button" onClick={() => studyStore.activate?.()} className={cn(pill, "border-brand/40 bg-brand-soft text-brand")}>
          I'm here
        </button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <button type="button" aria-label={label} title={label} className={pill}>
            <Timer aria-hidden className="h-4 w-4 text-text-secondary" />
            {session && status ? (
              <>
                <span aria-hidden className={cn("h-2 w-2 rounded-full", DOTS[status])} />
                <span aria-hidden className="hidden lg:inline">
                  {STATUS_LABELS[status]}
                </span>
                <span aria-hidden>{formatStudyTime(session.activeSeconds)}</span>
              </>
            ) : (
              <span aria-hidden className="hidden sm:inline">
                Study
              </span>
            )}
          </button>
        </DialogTrigger>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Study session</DialogTitle>
            <DialogDescription>
              Estimated study time: counted by PadhAI while you're active on the tutor or your files. An estimate, not a
              measure of attention.
            </DialogDescription>
          </DialogHeader>
          <StudySessionPanel />
          <Link
            href="/study"
            onClick={() => setOpen(false)}
            className="focus-ring self-start rounded text-sm font-semibold text-brand underline underline-offset-2"
          >
            See your Study Activity
          </Link>
        </DialogContent>
      </Dialog>
    </>
  );
}
