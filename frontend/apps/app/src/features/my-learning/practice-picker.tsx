"use client";

import { Button } from "@v1/ui/button";
import { ErrorState } from "@v1/ui/empty-state";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import Link from "next/link";
import { type FormEvent, useEffect, useId, useState } from "react";

import { Notice } from "@/features/settings/primitives";
import { describeError } from "@/lib/api/errors";
import { getPracticeTopics } from "@/lib/api/progress";
import type { PracticeBook, PracticeChapter, PracticeTopics } from "@/lib/api/types";
import { useAskInChat } from "./ask-in-chat";

const selectClass = "focus-field h-10 w-full rounded-xl border border-input bg-card px-3 text-sm disabled:opacity-60";
const link = "focus-ring rounded font-semibold text-brand underline underline-offset-2";

/** The plan's request wording (the API's `prompt`), for a chapter the student chose: the tutor sets a bank test. */
function practiceRequest(
  classLevel: number | null,
  subject: string,
  book: PracticeBook,
  chapter: PracticeChapter,
  topic: string | null,
): string {
  const where = `${classLevel === null ? "" : `Class ${classLevel} `}${subject} (${book.title}) Chapter ${chapter.number} "${chapter.title}"`;
  return `Test me on ${where}${topic ? `, topic "${topic}"` : ""}: 5 questions.`;
}

/**
 * Practice by chapter: subject, then chapter (grouped by book), then a topic or the whole chapter,
 * from the chapters the question bank has for the student's class (GET /v1/progress/practice-topics).
 * The button fills a new chat with the request; nothing is sent until the student presses Send.
 */
export function PracticePicker({ subjectName }: { subjectName: (code: string) => string }) {
  const ask = useAskInChat();
  const [topics, setTopics] = useState<PracticeTopics | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [subject, setSubject] = useState("");
  const [chapterId, setChapterId] = useState("");
  const [topicId, setTopicId] = useState("");
  const id = useId();

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getPracticeTopics(controller.signal).then(
      (loaded) => !controller.signal.aborted && setTopics(loaded),
      (failure) => !controller.signal.aborted && setError(failure),
    );
    return () => controller.abort();
  }, [attempt]);

  if (error) {
    return (
      <ErrorState
        title="Couldn't load the chapters"
        description={describeError(error).message}
        action={
          <Button variant="outline" onClick={() => setAttempt((count) => count + 1)}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!topics) {
    return (
      <SkeletonGroup label="Loading the chapters" className="space-y-3">
        <Skeleton className="h-10 w-full rounded-xl" />
        <Skeleton className="h-10 w-full rounded-xl" />
      </SkeletonGroup>
    );
  }
  if (!topics.available || !topics.subjects.length) {
    return topics.reason === "no_class" ? (
      <Notice>
        To practise by chapter, set your class (6 to 12) in{" "}
        <Link href="/settings/academic" className={link}>
          Academic Profile
        </Link>
        .
      </Notice>
    ) : (
      <Notice>There are no stored test questions for your class yet. You can still ask the tutor about any chapter.</Notice>
    );
  }

  const books = topics.subjects.find((entry) => entry.subjectCode === subject)?.books ?? [];
  const book = books.find((entry) => entry.chapters.some((chapter) => chapter.chapterId === chapterId));
  const chapter = book?.chapters.find((entry) => entry.chapterId === chapterId);
  const topic = chapter?.topics.find((entry) => entry.topicId === topicId);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!book || !chapter) return;
    ask(practiceRequest(topics.classLevel, subjectName(subject), book, chapter, topic?.title ?? null));
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={`${id}-subject`} className="text-sm font-bold text-foreground">
            Subject
          </label>
          <select
            id={`${id}-subject`}
            value={subject}
            onChange={(event) => {
              setSubject(event.target.value);
              setChapterId("");
              setTopicId("");
            }}
            className={selectClass}
          >
            <option value="">Choose a subject</option>
            {topics.subjects.map((entry) => (
              <option key={entry.subjectCode} value={entry.subjectCode}>
                {subjectName(entry.subjectCode)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={`${id}-chapter`} className="text-sm font-bold text-foreground">
            Chapter
          </label>
          <select
            id={`${id}-chapter`}
            value={chapterId}
            disabled={!subject}
            onChange={(event) => {
              setChapterId(event.target.value);
              setTopicId("");
            }}
            className={selectClass}
          >
            <option value="">Choose a chapter</option>
            {books.map((entry) => (
              <optgroup key={entry.bookId} label={entry.title}>
                {entry.chapters.map((item) => (
                  <option key={item.chapterId} value={item.chapterId}>
                    {item.number}. {item.title}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={`${id}-topic`} className="text-sm font-bold text-foreground">
            Topic <span className="font-normal text-text-secondary">(optional)</span>
          </label>
          <select
            id={`${id}-topic`}
            value={topicId}
            disabled={!chapter}
            onChange={(event) => setTopicId(event.target.value)}
            className={selectClass}
          >
            <option value="">Whole chapter</option>
            {chapter?.topics.map((item) => (
              <option key={item.topicId} value={item.topicId}>
                {item.number}. {item.title}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <Button type="submit" disabled={!chapter} aria-describedby={`${id}-hint`} className="w-full sm:w-auto">
          Practise in a new chat
        </Button>
        <p id={`${id}-hint`} className="text-2xs leading-relaxed text-text-secondary">
          Opens a new chat with your request filled in; nothing is sent until you press Send.
        </p>
      </div>
    </form>
  );
}
