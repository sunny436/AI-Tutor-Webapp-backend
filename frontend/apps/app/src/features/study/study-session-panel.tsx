"use client";

import { Button } from "@v1/ui/button";
import { ConfirmDialog } from "@v1/ui/confirm-dialog";
import { cn } from "@v1/ui/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { ChoiceGroup } from "@/features/settings/primitives";
import { useCatalog } from "@/features/settings/learning-data";
import { getStudyChapters } from "@/lib/api/study";
import { STUDY_ACTIVITIES, type StudyActivity, type StudyChapters, type StudySession } from "@/lib/api/types";
import { ACTIVITY_LABELS, formatStudyTime, isLearningView } from "./study-client";
import { type StudySnapshot, studyStore, useStudy } from "./study-store";

const selectClass = "focus-field h-10 w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm";

export type TabStatus = "studying" | "idle" | "prompting" | "paused" | "elsewhere" | "offline";

/** What this tab shows for the open session. Numbers never come from here: only words. */
export function tabStatus(study: StudySnapshot, pathname: string | null): TabStatus | null {
  const session = study.server?.session;
  if (!session) return null;
  if (session.status === "paused") return "paused";
  if (study.offline) return "offline";
  if (!isLearningView(pathname)) return "elsewhere";
  if (study.idle) return "idle";
  if (study.prompting) return "prompting";
  return "studying";
}

export const STATUS_LABELS: Record<TabStatus, string> = {
  studying: "Studying",
  idle: "Idle",
  prompting: "Still studying?",
  paused: "Paused",
  elsewhere: "Not counted on this page",
  offline: "Offline, not counted",
};

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** "ended at 10:42 (no study activity for 15 minutes)" and the like. */
export function endedNote(session: StudySession): string | null {
  if (!session.endedAt) return null;
  if (session.endReason === "stale") {
    // 15 minutes without study activity, or an hour paused: it ends at the last activity.
    return `Your study session ended at ${time(session.endedAt)}, after a while with no study activity.`;
  }
  if (session.endReason === "limit") return `Your study session ended at ${time(session.endedAt)}: sessions stop after 8 hours.`;
  return null;
}

function useSubjectName(): (code: string | null) => string {
  const { catalog } = useCatalog();
  return (code) => (code ? (catalog?.subjects.find((entry) => entry.code === code)?.name ?? code) : "No subject");
}

function contextLine(session: StudySession, subjectName: (code: string | null) => string): string {
  const segment = session.segment;
  if (!segment) return "";
  return [segment.subject ? subjectName(segment.subject) : null, segment.chapterTitle, ACTIVITY_LABELS[segment.activity]]
    .filter(Boolean)
    .join(" · ");
}

const CHAPTER_REASONS: Record<NonNullable<StudyChapters["reason"]>, string> = {
  no_class: "To choose a chapter, set your class (6 to 12) in Academic Profile.",
  unavailable: "Chapters can't be loaded right now. You can study without choosing one.",
  not_configured: "Chapters aren't available. You can study without choosing one.",
};

/** Subject, chapter (NCERT, optional) and activity: for starting a session or changing it. */
function ContextForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: StudySession["segment"];
  submitLabel: string;
  onSubmit: (context: { subject: string | null; chapterId: string | null; activity: StudyActivity }) => void;
  onCancel?: () => void;
}) {
  const { catalog } = useCatalog();
  const [subject, setSubject] = useState(initial?.subject ?? "");
  const [chapterId, setChapterId] = useState(initial?.chapterId ?? "");
  const [activity, setActivity] = useState<StudyActivity>(initial?.activity ?? "reading");
  const [chapters, setChapters] = useState<StudyChapters | "loading" | null>(null);
  const pending = useStudy().pending !== null;
  const id = useId();

  useEffect(() => {
    if (!subject) {
      setChapters(null);
      return;
    }
    const controller = new AbortController();
    setChapters("loading");
    getStudyChapters(subject, controller.signal).then(
      (loaded) => setChapters(loaded),
      () => !controller.signal.aborted && setChapters({ available: false, reason: "unavailable", chapters: [] }),
    );
    return () => controller.abort();
  }, [subject]);

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ subject: subject || null, chapterId: subject && chapterId ? chapterId : null, activity });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-subject`} className="text-sm font-bold text-foreground">
          Subject
        </label>
        <select
          id={`${id}-subject`}
          value={subject}
          onChange={(event) => {
            setSubject(event.target.value);
            setChapterId("");
          }}
          className={selectClass}
        >
          <option value="">No subject</option>
          {catalog?.subjects.map((entry) => (
            <option key={entry.code} value={entry.code}>
              {entry.name}
            </option>
          ))}
        </select>
      </div>
      {subject && (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-chapter`} className="text-sm font-bold text-foreground">
            Chapter <span className="font-normal text-text-secondary">(optional)</span>
          </label>
          <select
            id={`${id}-chapter`}
            value={chapterId}
            disabled={chapters === "loading" || !chapters?.available}
            onChange={(event) => setChapterId(event.target.value)}
            aria-describedby={chapters && chapters !== "loading" && !chapters.available ? `${id}-chapter-note` : undefined}
            className={cn(selectClass, "disabled:opacity-60")}
          >
            <option value="">{chapters === "loading" ? "Loading chapters…" : "No chapter"}</option>
            {chapters !== "loading" &&
              chapters?.chapters.map((chapter) => (
                <option key={chapter.chapterId} value={chapter.chapterId}>
                  {chapter.number !== null ? `${chapter.number}. ` : ""}
                  {chapter.title}
                </option>
              ))}
          </select>
          {chapters && chapters !== "loading" && !chapters.available && chapters.reason && (
            <p id={`${id}-chapter-note`} className="text-2xs text-text-secondary">
              {CHAPTER_REASONS[chapters.reason]}
              {chapters.reason === "no_class" && (
                <>
                  {" "}
                  <Link href="/settings/academic" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
                    Set your class
                  </Link>
                </>
              )}
            </p>
          )}
        </div>
      )}
      <ChoiceGroup
        legend="What are you doing?"
        value={activity}
        options={STUDY_ACTIVITIES.map((value) => ({ value, label: ACTIVITY_LABELS[value] }))}
        onChange={setActivity}
      />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

function Seconds({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex min-w-0 flex-col-reverse">
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="font-display text-lg font-bold tabular-nums text-foreground">{formatStudyTime(value)}</dd>
    </div>
  );
}

/**
 * The session's controls: start, pause, resume, change, end. The same panel in the header's
 * dialog and on Study Activity. Times are the server's, as of its last answer (every 30 s).
 */
export function StudySessionPanel() {
  const study = useStudy();
  const pathname = usePathname();
  const subjectName = useSubjectName();
  const [changing, setChanging] = useState(false);
  const [ending, setEnding] = useState(false);
  const session = study.server?.session ?? null;
  const lastEnded = study.server?.lastEnded ?? null;
  const status = tabStatus(study, pathname);
  const note = lastEnded && lastEnded.id !== study.dismissedEnded ? endedNote(lastEnded) : null;

  if (!study.server) {
    return study.loadError ? (
      <p role="alert" className="text-sm text-text-secondary">
        Study time can't be loaded right now.{" "}
        <button type="button" onClick={() => void studyStore.refresh()} className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
          Try again
        </button>
      </p>
    ) : (
      <p className="text-sm text-text-secondary">Loading your study session…</p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {study.actionError && (
        <p role="alert" className="rounded-xl border border-accent-warm/30 bg-accent-warm-soft px-3.5 py-2.5 text-sm text-foreground">
          {study.actionError}
        </p>
      )}
      {!session && note && lastEnded && (
        <div role="status" className="rounded-xl border border-border bg-surface px-3.5 py-3 text-sm text-foreground">
          <p>{note}</p>
          <p className="mt-1 text-text-secondary">It counted {formatStudyTime(lastEnded.activeSeconds)} of estimated study time.</p>
          <button
            type="button"
            onClick={() => studyStore.dismissEnded(lastEnded.id)}
            className="focus-ring mt-2 rounded text-sm font-semibold text-brand underline underline-offset-2"
          >
            Dismiss
          </button>
        </div>
      )}

      {!session ? (
        <>
          <p className="text-sm text-text-secondary">
            Start a session when you sit down to study. Time counts only while this page is on screen, on the tutor or your
            files, and you're active.
          </p>
          <ContextForm
            submitLabel="Start studying"
            onSubmit={(context) => void studyStore.start(context)}
          />
        </>
      ) : changing ? (
        <ContextForm
          initial={session.segment}
          submitLabel="Save"
          onSubmit={(context) => {
            setChanging(false);
            void studyStore.changeContext(context);
          }}
          onCancel={() => setChanging(false)}
        />
      ) : (
        <>
          <div>
            <p className="text-sm font-semibold text-foreground" aria-live="polite">
              {status ? STATUS_LABELS[status] : ""}
            </p>
            <p className="text-sm text-text-secondary">{contextLine(session, subjectName)}</p>
          </div>
          {status === "prompting" && (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl border border-brand/20 bg-brand-soft px-3.5 py-2.5 text-sm">
              <span>Still studying? Without a reply, this tab stops counting in a moment.</span>
              <Button size="sm" onClick={() => studyStore.activate?.()}>
                Yes, I'm here
              </Button>
            </div>
          )}
          <dl className="grid grid-cols-3 gap-3">
            <Seconds label="estimated study" value={session.activeSeconds} />
            <Seconds label="idle" value={session.idleSeconds} />
            <Seconds label="paused" value={session.pausedSeconds} />
          </dl>
          <div className="flex flex-wrap gap-2">
            {session.status === "paused" ? (
              <Button disabled={study.pending !== null} onClick={() => void studyStore.transition("resume")}>
                Resume
              </Button>
            ) : (
              <Button variant="outline" disabled={study.pending !== null} onClick={() => void studyStore.transition("pause")}>
                Pause
              </Button>
            )}
            <Button variant="outline" disabled={study.pending !== null} onClick={() => setChanging(true)}>
              Change subject or activity
            </Button>
            <Button variant="ghost" disabled={study.pending !== null} onClick={() => setEnding(true)}>
              End session
            </Button>
          </div>
          <ConfirmDialog
            open={ending}
            onOpenChange={setEnding}
            title="End this study session?"
            description={`It has ${formatStudyTime(session.activeSeconds)} of estimated study time so far. You can start a new one any time.`}
            confirmLabel="End session"
            pending={study.pending === "end"}
            onConfirm={async () => {
              await studyStore.transition("end");
              setEnding(false);
            }}
          />
        </>
      )}
    </div>
  );
}
