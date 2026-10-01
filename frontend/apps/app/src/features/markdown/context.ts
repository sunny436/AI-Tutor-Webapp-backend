import { createContext } from "react";

import type { Assessment, AssessmentResponseRequest, Citation } from "@/lib/api/types";

/**
 * True only for the last block of a reply that is still streaming. Widgets that need their
 * whole source (a diagram, a chart, a quiz) wait for it instead of drawing half of it.
 */
export const LiveContext = createContext(false);

/**
 * What the reply's [1] and [F1] markers point at. `undefined` = not known yet (the reply is
 * still streaming, or it came from before citations existed): never "missing".
 */
export const CitationsContext = createContext<Citation[] | undefined>(undefined);

/** A typed command that reached a reply's test (chat-store.ts): the card shows it and scrolls to it. */
export type TestNotice = { position: number; text: string; seq: number };

/**
 * A reply's practice test as the server recorded it, for the card that draws it (widgets/quiz.tsx).
 * `null` outside a chat reply. While the reply is still being written there is no test yet.
 */
export type TestState = {
  streaming: boolean;
  assessments: readonly Assessment[];
  /** Why the reply's test was not accepted (no test was kept). */
  error: string | null;
  notice: TestNotice | null;
  respond: (position: number, request: Omit<AssessmentResponseRequest, "position">) => Promise<void>;
};

export const TestContext = createContext<TestState | null>(null);
