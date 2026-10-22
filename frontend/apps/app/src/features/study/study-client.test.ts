import { afterEach, describe, expect, mock, test } from "bun:test";

import { ApiError } from "@/lib/api/errors";
import { ROUTES } from "@/lib/api/routes";
import { getStudySummary, sendStudyBeat } from "@/lib/api/study";
import type { StudyBeat, StudySession, StudyState } from "@/lib/api/types";
import { RANGES } from "./study-activity-view";
import {
  ActivityRun,
  formatStudyTime,
  idleTimeoutMs,
  isEligible,
  isLearningView,
  promptBeforeIdleMs,
  sendWithRetry,
} from "./study-client";
import { tabStatus } from "./study-session-panel";
import { type StudySnapshot, studyStore } from "./study-store";

const IDLE = { readingSeconds: 300, solvingSeconds: 120 };

function session(status: StudySession["status"], segmentId = "33333333-3333-4333-8333-333333333333"): StudySession {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    status,
    startedAt: "2026-10-15T04:00:00Z",
    pausedAt: status === "paused" ? "2026-10-15T04:10:00Z" : null,
    endedAt: status === "ended" ? "2026-10-15T04:20:00Z" : null,
    endReason: status === "ended" ? "ended" : null,
    timezone: "Asia/Kolkata",
    segment:
      status === "ended"
        ? null
        : {
            id: segmentId,
            kind: status === "paused" ? "paused" : "study",
            subject: "science",
            chapterId: null,
            bookId: null,
            chapterTitle: null,
            activity: "reading",
            startedAt: "2026-10-15T04:00:00Z",
          },
    activeSeconds: 540,
    idleSeconds: 60,
    pausedSeconds: status === "paused" ? 30 : 0,
    durationSeconds: status === "paused" ? 630 : 600,
  };
}

function state(current: StudySession | null): StudyState {
  return { session: current, lastEnded: null, idle: IDLE, serverTime: "2026-10-15T04:20:00Z" };
}

const BEAT: StudyBeat = {
  beatId: "22222222-2222-4222-8222-222222222222",
  clientId: "44444444-4444-4444-8444-444444444444",
  wasActive: true,
  nowActive: true,
  studyView: true,
  visible: true,
};

describe("what this tab reports", () => {
  test("a run is credited only after it has been seen to start", () => {
    const run = new ActivityRun(false);
    expect(run.update(true)).toBe(true);
    const opened = run.observe();
    expect(opened).toMatchObject({ wasActive: false, nowActive: true });
    run.received(opened);
    expect(run.observe()).toMatchObject({ wasActive: true, nowActive: true });
  });

  test("going idle, hidden or elsewhere sends the edge at once: active until now, inactive from now", () => {
    const run = new ActivityRun(false);
    run.update(true);
    run.received(run.observe());
    expect(run.update(false)).toBe(true);
    const edge = run.observe();
    expect(edge).toMatchObject({ wasActive: true, nowActive: false });
    run.received(edge);
    expect(run.observe()).toMatchObject({ wasActive: false, nowActive: false });
    expect(run.update(false)).toBe(false); // no change: no extra beat
  });

  test("a gap never hides inside a run: back before the edge was sent still reports the gap", () => {
    const run = new ActivityRun(false);
    run.update(true);
    run.received(run.observe());
    run.update(false);
    run.update(true);
    expect(run.observe()).toMatchObject({ wasActive: false, nowActive: true });
  });

  test("an answer for an older beat cannot reopen a run that had a gap since", () => {
    const run = new ActivityRun(false);
    run.update(true);
    const sent = run.observe();
    run.update(false);
    run.update(true);
    run.received(sent);
    expect(run.observe().wasActive).toBe(false);
  });

  test("a lost beat while active costs nothing; a lost edge is never claimed later", () => {
    const active = new ActivityRun(false);
    active.update(true);
    active.received(active.observe());
    active.lost();
    expect(active.observe().wasActive).toBe(true);

    const idle = new ActivityRun(false);
    idle.update(true);
    idle.received(idle.observe());
    idle.update(false);
    idle.lost(); // the edge never arrived
    idle.update(true);
    expect(idle.observe().wasActive).toBe(false);
  });

  test("study actions are observations: start and resume open a run, pause and end close it", () => {
    const run = new ActivityRun(false);
    run.update(true);
    run.acted(true);
    expect(run.observe().wasActive).toBe(true);
    run.acted(false);
    expect(run.observe().wasActive).toBe(false);
  });

  test("eligible means visible, on a learning view, online, running and not idle: nothing else", () => {
    const yes = { visible: true, studyView: true, online: true, running: true, idle: false };
    expect(isEligible(yes)).toBe(true);
    for (const key of ["visible", "studyView", "online", "running"] as const) {
      expect(isEligible({ ...yes, [key]: false })).toBe(false);
    }
    expect(isEligible({ ...yes, idle: true })).toBe(false);
  });

  test("learning views are the tutor and the File Library", () => {
    for (const path of ["/", "/c/11111111-1111-4111-8111-111111111111", "/library"]) expect(isLearningView(path)).toBe(true);
    for (const path of ["/settings/profile", "/study", "/learning", "/help", "/about", "/library-old", null]) {
      expect(isLearningView(path)).toBe(false);
    }
  });

  test("idle limits come from the server; the reading prompt always comes before idle", () => {
    expect(idleTimeoutMs(IDLE, "reading")).toBe(300_000);
    expect(idleTimeoutMs(IDLE, "revision")).toBe(300_000);
    expect(idleTimeoutMs(IDLE, "practice")).toBe(120_000);
    expect(idleTimeoutMs({ readingSeconds: 60, solvingSeconds: 30 }, "test")).toBe(30_000);
    expect(promptBeforeIdleMs(300_000, "reading")).toBe(30_000);
    expect(promptBeforeIdleMs(40_000, "reading")).toBe(20_000);
    expect(promptBeforeIdleMs(120_000, "practice")).toBe(0);
  });

  test("an uncertain answer is retried once with the same beat; a certain one never", async () => {
    const seen: string[] = [];
    const flaky = mock(async (beat: StudyBeat) => {
      seen.push(beat.beatId);
      if (seen.length === 1) throw new ApiError(0, "network_error");
      return state(null);
    });
    await sendWithRetry(BEAT, flaky);
    expect(seen).toEqual([BEAT.beatId, BEAT.beatId]);

    const refused = mock(async () => {
      throw new ApiError(422, "validation_error");
    });
    await expect(sendWithRetry(BEAT, refused)).rejects.toBeInstanceOf(ApiError);
    expect(refused).toHaveBeenCalledTimes(1);

    const down = mock(async () => {
      throw new ApiError(0, "network_error");
    });
    await expect(sendWithRetry(BEAT, down)).rejects.toBeInstanceOf(ApiError);
    expect(down).toHaveBeenCalledTimes(2);
  });

  test("times are the server's, in whole minutes rounded down once", () => {
    expect(formatStudyTime(0)).toBe("0 min");
    expect(formatStudyTime(59)).toBe("under 1 min");
    expect(formatStudyTime(119)).toBe("1 min");
    expect(formatStudyTime(3599)).toBe("59 min");
    expect(formatStudyTime(3900)).toBe("1 h 05 min");
  });
});

describe("the status this tab shows", () => {
  const base: StudySnapshot = {
    server: state(session("active")),
    loadError: null,
    idle: false,
    prompting: false,
    offline: false,
    pending: null,
    actionError: null,
    dismissedEnded: null,
  };

  test("from the server's state and this tab's facts", () => {
    expect(tabStatus({ ...base, server: state(null) }, "/")).toBeNull();
    expect(tabStatus(base, "/")).toBe("studying");
    expect(tabStatus(base, "/settings/profile")).toBe("elsewhere");
    expect(tabStatus({ ...base, idle: true }, "/")).toBe("idle");
    expect(tabStatus({ ...base, prompting: true }, "/")).toBe("prompting");
    expect(tabStatus({ ...base, offline: true }, "/")).toBe("offline");
    expect(tabStatus({ ...base, server: state(session("paused")), idle: true }, "/")).toBe("paused");
  });
});

describe("the session's store", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    studyStore.flush = null;
    studyStore.acted = null;
    studyStore.set({ server: null, loadError: null, actionError: null, pending: null });
  });

  function serve(routes: Record<string, () => Response>) {
    const calls: string[] = [];
    globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${new URL(String(input), "http://app.test").pathname}`;
      calls.push(key);
      const respond = Object.entries(routes).find(([pattern]) => key.startsWith(pattern))?.[1];
      if (!respond) throw new Error(`unexpected ${key}`);
      return respond();
    }) as unknown as typeof fetch;
    return calls;
  }

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  test("pause reports this tab's time first, then shows the server's paused session", async () => {
    studyStore.apply(state(session("active")));
    const order: string[] = [];
    studyStore.flush = async () => {
      order.push("flush");
    };
    const acted = mock((_active: boolean) => undefined);
    studyStore.acted = acted;
    const calls = serve({ "POST /api/v1/study/session/": () => json(state(session("paused"))) });
    await studyStore.transition("pause");
    order.push(...calls);
    expect(order).toEqual(["flush", "POST /api/v1/study/session/11111111-1111-4111-8111-111111111111/pause"]);
    expect(studyStore.get().server?.session?.status).toBe("paused");
    expect(acted).toHaveBeenCalledWith(false);
  });

  test("resume opens a run; a double click sends one request", async () => {
    studyStore.apply(state(session("paused")));
    const acted = mock((_active: boolean) => undefined);
    studyStore.acted = acted;
    const calls = serve({ "POST /api/v1/study/session/": () => json(state(session("active", "55555555-5555-4555-8555-555555555555"))) });
    await Promise.all([studyStore.transition("resume"), studyStore.transition("resume")]);
    expect(calls).toHaveLength(1);
    expect(studyStore.get().server?.session?.status).toBe("active");
    expect(acted).toHaveBeenCalledWith(true);
  });

  test("changed on another tab or device (409): the server's state is reloaded and said so", async () => {
    studyStore.apply(state(session("active")));
    serve({
      "POST /api/v1/study/session/": () =>
        json({ error: { code: "study_state_changed", message: "changed", requestId: "r1" } }, 409),
      "GET /api/v1/study/session": () => json(state(session("paused"))),
    });
    await studyStore.transition("pause");
    expect(studyStore.get().server?.session?.status).toBe("paused");
    expect(studyStore.get().actionError).toContain("another tab or device");
  });

  test("after a refresh the server's state is shown; a failed reload keeps what was known", async () => {
    serve({ "GET /api/v1/study/session": () => json(state(session("active"))) });
    await studyStore.refresh();
    expect(studyStore.get().server?.session?.activeSeconds).toBe(540);
    serve({ "GET /api/v1/study/session": () => json({ error: { code: "internal_error", message: "x", requestId: "r" } }, 500) });
    await studyStore.refresh();
    expect(studyStore.get().server?.session?.activeSeconds).toBe(540);
    expect(studyStore.get().loadError).toBeNull();
    studyStore.set({ server: null });
    await studyStore.refresh();
    expect(studyStore.get().loadError).toBeInstanceOf(ApiError);
  });

  test("a beat says nothing about who the student is: the session cookie does", async () => {
    let body: Record<string, unknown> = {};
    globalThis.fetch = mock(async (_input: RequestInfo | URL, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return json(state(null));
    }) as unknown as typeof fetch;
    await sendStudyBeat(BEAT);
    expect(Object.keys(body).sort()).toEqual(["beatId", "clientId", "nowActive", "studyView", "visible", "wasActive"]);
    const study = Object.entries(ROUTES).filter(([key]) => key.includes("/v1/study/"));
    expect(study.length).toBe(9);
    expect(study.every(([, spec]) => spec.auth)).toBe(true);
  });

  test("the date filters ask the server for today, 7 or 30 days", async () => {
    expect(RANGES.map((range) => range.value)).toEqual(["1", "7", "30"]);
    let url = "";
    globalThis.fetch = mock(async (input: RequestInfo | URL) => {
      url = String(input);
      return json({});
    }) as unknown as typeof fetch;
    await getStudySummary(30);
    expect(url).toBe("/api/v1/study/summary?days=30");
  });
});
