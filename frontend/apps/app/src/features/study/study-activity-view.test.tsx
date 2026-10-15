import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { ApiError } from "@/lib/api/errors";
import type { StudySummary } from "@/lib/api/types";
import { StudySummaryContent } from "./study-activity-view";

const NAMES: Record<string, string> = { science: "Science", mathematics: "Mathematics" };
const subjectName = (code: string | null) => (code ? (NAMES[code] ?? code) : "No subject chosen");

const render = (summary: StudySummary | null, error: unknown = null, days = 7) =>
  renderToStaticMarkup(
    <StudySummaryContent summary={summary} error={error} days={days} subjectName={subjectName} onRetry={() => undefined} />,
  );

const SUMMARY: StudySummary = {
  timezone: "Asia/Kolkata",
  from: "2026-10-09",
  to: "2026-10-15",
  firstRecordedDate: "2026-10-13",
  totals: { activeSeconds: 3900, idleSeconds: 600, pausedSeconds: 300, appSeconds: 7200, sessions: 2 },
  days: [
    { date: "2026-10-13", activeSeconds: 1200, idleSeconds: 0, pausedSeconds: 0, appSeconds: 1800 },
    { date: "2026-10-14", activeSeconds: 0, idleSeconds: 0, pausedSeconds: 0, appSeconds: 600 },
    { date: "2026-10-15", activeSeconds: 2700, idleSeconds: 600, pausedSeconds: 300, appSeconds: 4800 },
  ],
  subjects: [
    { subject: "science", activeSeconds: 3000 },
    { subject: null, activeSeconds: 900 },
  ],
  chapters: [
    { subject: "science", chapterId: "sci-8-en-ch02", bookId: "sci-8-en", chapterTitle: "Microorganisms", activeSeconds: 1800 },
  ],
  activities: [
    { activity: "reading", activeSeconds: 2400 },
    { activity: "practice", activeSeconds: 1500 },
  ],
  sessions: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      status: "ended",
      endReason: "stale",
      startedAt: "2026-10-15T04:00:00Z",
      endedAt: "2026-10-15T05:00:00Z",
      activeSeconds: 2700,
      idleSeconds: 600,
      pausedSeconds: 300,
      durationSeconds: 3600,
      subjects: ["science"],
      chapters: ["Microorganisms"],
      activities: ["reading", "practice"],
    },
  ],
};

describe("Study Activity", () => {
  test("loading, error with a retry, and nothing recorded yet", () => {
    expect(render(null)).toContain("Loading your study activity");
    const failed = render(null, new ApiError(0, "network_error"));
    expect(failed).toContain("Couldn&#x27;t load your study activity");
    expect(failed).toContain("Try again");
    expect(render({ ...SUMMARY, firstRecordedDate: null, days: [], sessions: [] })).toContain("Nothing recorded yet");
  });

  test("study time and time in PadhAI are separate numbers; active, idle and paused are explained", () => {
    const html = render(SUMMARY);
    expect(html).toContain("1 h 05 min");
    expect(html).toContain("estimated study time");
    expect(html).toContain("2 h 00 min");
    expect(html).toContain("time in PadhAI");
    expect(html).toContain("10 min");
    expect(html).toContain("5 min");
    expect(html).toContain("no activity was seen");
  });

  test("days before anything was recorded are said to have no data, not shown as zero", () => {
    const html = render(SUMMARY);
    expect(html).toContain("earlier days have no data");
    expect(html.match(/role="img"/g)).toHaveLength(SUMMARY.days.length);
    expect(html).toContain("Estimated study minutes, last 3 days");
  });

  test("by subject, chapter and activity, and the recent sessions", () => {
    const html = render(SUMMARY);
    expect(html).toContain("Science");
    expect(html).toContain("No subject chosen");
    expect(html).toContain("Microorganisms (Science)");
    expect(html).toContain("Reading");
    expect(html).toContain("Practice");
    expect(html).toContain("Ended (no study activity)");
    expect(html).toContain("45 min study · 1 h 00 min long");
  });

  test("today alone has no trend chart", () => {
    const today = { ...SUMMARY, days: SUMMARY.days.slice(-1) };
    expect(render(today, null, 1)).not.toContain('role="img"');
  });
});
