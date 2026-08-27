"use client";

/**
 * Consult  -  the AI consultation chat.
 *
 * The flow the user sees:
 *   1. type ONE sentence ("I have acidity")
 *   2. the AI decides what it needs to know and returns question cards
 *   3. tap the options, press Continue
 *   4. read the plan
 *
 * The questions and their options are generated per condition by the backend  - 
 * acidity, migraine and PCOS each produce a different form. Nothing here is
 * disease-specific.
 *
 * `?c=<sessionId>` reopens a saved chat, restoring a half-finished intake from
 * the state persisted on the last assistant message.
 */

import { useAuthToken } from "@convex-dev/auth/react";
import { api } from "@v1/backend/convex/_generated/api";
import { useMutation, useQuery } from "convex/react";
import {
  AlertTriangle,
  FileText,
  Leaf,
  Loader2,
  Paperclip,
  SendHorizonal,
  ShieldAlert,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ConsultUnavailableError,
  postConsult,
  postConsultStream,
  uploadDocument,
} from "@/lib/consult/client";
import { CONSULTING } from "@/lib/consult/types";
import type {
  ConsultContext,
  ConsultResult,
  ConsultSource,
  PersistedConsultState,
} from "@/lib/consult/types";
import { AnswerSections } from "./_components/answer-sections";
// `AnswerSources` is deliberately NOT imported. The file stays on disk,
// unreferenced, so restoring citations is one import and one line.
// NOTE: `IntakePanel`, `QuestionCard` and `OptionChip` are deliberately NOT
// imported any more. The files stay on disk, unreferenced, so this change is one
// revert rather than a resurrection; they go in a later commit once the
// conversational flow has run on real traffic.

/**
 * `id` is what React reconciles on, and it has to be assigned when the turn is
 * CREATED rather than derived from its position.
 *
 * The list was keyed by array index while turns are both appended and removed
 * from the end (`dropStreamingPlaceholder` slices the last one off), which is
 * the combination React documents as unsafe: the component instance sitting at
 * index 4 is reused for whatever turn lands at index 4 next, carrying its local
 * state onto different content.
 *
 * The original offender was the intake panel, which held its own `useState` for
 * the selected chips — a set of taps could end up attached to a different set of
 * questions. That panel is gone with the card flow, but the hazard is not: the
 * streaming placeholder is still appended and sliced off the end, and bubbles
 * still hold local state. Stable ids stay.
 */
type Turn = { id: string } & (
  | { who: "user"; text: string }
  | {
      who: "bot";
      kind: "chat" | "answer" | "escalation" | "error";
      text: string;
      /** True while tokens are still arriving, so the bubble can show it. */
      streaming?: boolean;
      /** An expired login is not an outage — see the banner below. */
      reason?: "service" | "session" | "signed_out";
      /** Which knowledge notes this answer was drawn from. */
      sources?: ConsultSource[];
    }
);

/** Phases where a typed message is extra detail rather than a new message. */
const IN_CONSULTATION = new Set<string>(CONSULTING);

/**
 * Opening lines for an empty chat.
 *
 * Every one of these has a note behind it in `data/knowledge/` — acidity,
 * insomnia, gas/bloating and hair-fall are four of the twenty-nine — so tapping
 * one leads to a grounded answer rather than the model improvising. Written the
 * way people type, which is also how the `aliases:` field in those same notes is
 * written ("neend nahi aati", "khatti dakar", "baal jhadna").
 */
const STARTERS = [
  "Acidity ho rahi hai",
  "Neend nahi aati",
  "Gas aur bloating",
  "Baal jhad rahe hain",
] as const;

function newId() {
  try {
    return crypto.randomUUID();
  } catch {
    return `s_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  }
}

// Module scope on purpose: it must keep counting across a remount, so a turn
// rendered before a navigation can never collide with one created after it.
let turnSeq = 0;
const nextTurnId = () => `turn_${++turnSeq}`;

function BotBubble({ children }: { children: React.ReactNode }) {
  return (
    // No max-width here: the assistant's turn is the reading column and is
    // constrained by the page, not by a bubble. Capping it at 94% left a ragged
    // right edge that made long answers look like chat messages rather than
    // written guidance.
    <div className="flex animate-rise-in gap-3">
      {/* `bg-brand`, not an emerald→teal gradient. The app had eight hand-rolled
          copies of that gradient competing with the token-driven <Button> on the
          same screens — two primary treatments, neither of which was the design
          system's. */}
      <span
        aria-hidden
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground elev-1"
      >
        <Leaf className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function ConsultInner() {
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Reactive to URL changes, which is the whole point. This used to be a
  // useState filled by a mount-only effect:
  //
  //     useEffect(() => { setUrlSession(...search.get("c")) }, [])
  //
  // Clicking a chat in the sidebar is a client-side navigation  -  the URL
  // changes but this component never unmounts, so that effect never re-ran and
  // the page kept showing the previous conversation. "New Chat" appeared to
  // work only because it happened to force a remount.
  //
  // The Suspense boundary this hook needs is already in place (see the default
  // export below), so reading the param properly costs nothing.
  const urlSession = useSearchParams().get("c");

  const saveMsg = useMutation(api.chats.save);
  const messages = useQuery(api.chats.getMessages, urlSession ? { sessionId: urlSession } : "skip");

  const [turns, setTurns] = useState<Turn[]>([]);
  const [context, setContext] = useState<ConsultContext | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // The Convex login token. The backend verifies it and uses the subject to
  // decide whose uploaded reports may be searched; without it the consultation
  // still works, just against the shared knowledge base only.
  const token = useAuthToken();

  const [uploading, setUploading] = useState(false);
  const [documents, setDocuments] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  /**
   * Which conversation is on screen RIGHT NOW.
   *
   * `sessionId` cannot answer that question from inside an in-flight request:
   * the closure captured its value at send time. A card set takes ~17s, which is
   * a wide enough window to send in chat A, open chat B from the sidebar, and
   * have A's answer append itself to B's transcript — and, worse, have A's
   * consultation context become B's, so B's next message continues A's intake
   * under the wrong condition.
   *
   * The database was never affected: `persist(sid, …)` captured `sid` the same
   * way and always wrote to the right chat. Only the screen went wrong, which is
   * the harder kind to notice.
   */
  const onScreenRef = useRef<string | null>(null);

  /**
   * Rehydrate a saved chat. The transcript alone is not enough  -  without the
   * persisted `state` the next message would restart the consultation from
   * scratch, which is exactly what the old page did.
   */
  const loadedRef = useRef<string | null>(null);
  useEffect(() => {
    const key = urlSession ?? "new";
    // Before the early returns, deliberately. The conversation on screen changes
    // the moment the URL does — waiting until the transcript has loaded would
    // leave a window in which an in-flight reply still believes it belongs here.
    onScreenRef.current = urlSession;
    if (loadedRef.current === key) return;

    if (!urlSession) {
      loadedRef.current = key;
      setSessionId(null);
      setTurns([]);
      setContext(null);
      return;
    }
    if (messages === undefined) return; // wait for the query; effect re-runs
    loadedRef.current = key;
    setSessionId(urlSession);

    const restored: Turn[] = [];
    let lastContext: ConsultContext | null = null;

    for (const message of messages) {
      if (message.role === "user") {
        restored.push({ id: nextTurnId(), who: "user", text: message.content });
        continue;
      }
      let state: PersistedConsultState | null = null;
      try {
        state = message.state ? (JSON.parse(message.state) as PersistedConsultState) : null;
      } catch {
        state = null; // an unreadable blob just means "no resume", never a crash
      }
      if (state?.context) lastContext = state.context;

      // A stored `intake` means this conversation was held before the card flow
      // was replaced. Its question set is NOT re-rendered — the consultation
      // continues in prose from here — but the message text is kept, so the
      // transcript still reads as the history it actually was.
      const kind =
        message.kind === "escalation" || message.kind === "chat" || message.kind === "intake"
          ? ((message.kind === "intake" ? "chat" : message.kind) as "escalation" | "chat")
          : "answer";
      restored.push({
        id: nextTurnId(),
        who: "bot",
        kind,
        text: message.content,
        sources: state?.sources,
      });
    }

    setTurns(restored);
    setContext(lastContext);
  }, [urlSession, messages]);

  const persist = useCallback(
    (sid: string, result: ConsultResult) => {
      const state: PersistedConsultState = {
        v: 1,
        context: result.context,
        intake: result.intake ?? null,
        // Stored so citations survive a reload. Without it, reopening a
        // consultation showed the plan with its provenance silently missing —
        // worse than never showing it, because the reader cannot tell "no
        // sources" from "sources were dropped on the way to storage".
        sources: result.sources?.length ? result.sources : undefined,
      };
      saveMsg({
        sessionId: sid,
        role: "assistant",
        content: result.kind === "intake" ? result.message || "A few quick questions" : result.answer,
        kind: result.kind,
        state: JSON.stringify(state),
      }).catch(() => {});
    },
    [saveMsg],
  );

  /** Apply one backend turn to the transcript. */
  const apply = useCallback((result: ConsultResult) => {
    setContext(result.context);
    setTurns((current) => {
      // `kind: "intake"` is no longer produced by the backend — gathering
      // questions arrive as ordinary `chat` turns. The mapping below is kept
      // total rather than assuming that, so an in-flight response from an older
      // server renders as a message instead of vanishing.
      const kind =
        result.kind === "escalation" || result.kind === "chat" || result.kind === "error"
          ? result.kind
          : "answer";
      return [
        ...current,
        { id: nextTurnId(), who: "bot", kind, text: result.answer, sources: result.sources },
      ];
    });
  }, []);

  const failed = (error: unknown) => {
    const known = error instanceof ConsultUnavailableError ? error : null;
    const message = known ? known.message : "Something went wrong. Please try again.";
    toast.error(message);
    // Same reasoning as the server-reported outage above: this is a failure, not
    // a reply, so it gets the warning banner rather than a chat bubble.
    setTurns((current) => [
      ...current,
      {
        id: nextTurnId(),
        who: "bot",
        kind: "error",
        text: message,
        reason: known?.reason ?? "service",
      },
    ]);
  };

  /**
   * Grow ONE placeholder bubble as tokens arrive.
   *
   * Appending a turn per chunk would produce a hundred bubbles; replacing the
   * transcript would lose the user's message. So the first token creates a
   * single streaming turn and every token after it extends that same turn's
   * text. `dropStreamingPlaceholder` removes it once the real result is in
   * hand, so exactly one assistant turn ever reaches the transcript.
   */
  const streamToken = useCallback((piece: string) => {
    setTurns((current) => {
      const last = current[current.length - 1];
      if (last && last.who === "bot" && "streaming" in last && last.streaming) {
        // Same `id`, deliberately: this is one bubble growing, not a new turn.
        return [...current.slice(0, -1), { ...last, text: last.text + piece }];
      }
      return [
        ...current,
        { id: nextTurnId(), who: "bot", kind: "answer", text: piece, streaming: true },
      ];
    });
  }, []);

  const dropStreamingPlaceholder = useCallback(() => {
    setTurns((current) => {
      const last = current[current.length - 1];
      if (last && last.who === "bot" && "streaming" in last && last.streaming) {
        return current.slice(0, -1);
      }
      return current;
    });
  }, []);

  /**
   * Start (or restart) a consultation from a typed sentence.
   *
   * `refocus` is only true when the send button was activated from the keyboard.
   * Pressing Enter never moves focus out of the composer, so it needs nothing;
   * clicking the button does, and a keyboard user was left having to tab the
   * whole page again for every message. Restoring focus on a touch tap would
   * force the on-screen keyboard back open, so the caller distinguishes the two.
   */
  const send = async (raw: string, refocus = false) => {
    const text = raw.trim();
    if (!text || busy) return;
    setInput("");
    if (refocus) composerRef.current?.focus();

    let sid = sessionId;
    if (!sid) {
      sid = newId();
      // Claim the id BEFORE it reaches the URL.
      //
      // Putting `?c=<sid>` in the address bar changes `urlSession` (Next 14
      // keeps useSearchParams in step with replaceState), which starts a
      // getMessages query for a session Convex has not been told about yet. The
      // rehydrate effect below then saw a brand-new key, got back an empty list,
      // and called setTurns([]) — wiping the greeting and the message the user
      // had just typed. The reply arrived afterwards and was appended to the
      // empty transcript, which is exactly what the bug report showed.
      //
      // `saveMsg` is deliberately not awaited (the turn should not wait on a
      // write), so the race is real rather than theoretical. Marking the id as
      // already loaded is what closes it: this tab is the authority on a session
      // it just created, and there is nothing on the server to restore.
      loadedRef.current = sid;
      onScreenRef.current = sid;
      setSessionId(sid);
      // Put the session in the URL so a refresh keeps the chat and the sidebar
      // can highlight it.
      window.history.replaceState({}, "", `?c=${sid}`);
    }

    setTurns((current) => [...current, { id: nextTurnId(), who: "user", text }]);
    saveMsg({ sessionId: sid, role: "user", content: text }).catch(() => {});

    // Typing during a consultation is extra detail; otherwise the message gets
    // routed. Either way the context MUST go along  -  it carries the conversation
    // memory, and without it every message looked like the first one, so the
    // assistant kept re-greeting and re-asking what was wrong.
    const inConsultation = IN_CONSULTATION.has(context?.phase ?? "idle");
    setBusy(true);
    try {
      const result = await postConsultStream(
        // `conversationId` is `sid`, not `sessionId`: inside an in-flight
        // request the closure holds the value captured at send time, and `sid`
        // is the one this turn actually belongs to. Same reasoning as `persist`
        // below, which is already addressed to `sid` for exactly this reason.
        inConsultation
          ? { context, freeText: text, conversationId: sid }
          : { problem: text, context, conversationId: sid },
        // Tokens stop reaching the screen the instant the reader opens another
        // chat; the request itself is left to finish, because an answer already
        // paid for should be waiting in the chat that asked for it.
        (piece) => {
          if (onScreenRef.current === sid) streamToken(piece);
        },
        undefined,
        token,
      );
      // Save first and render second. `persist` is addressed to `sid`, so it is
      // always correct; only the screen has to be told apart.
      persist(sid, result);
      if (onScreenRef.current !== sid) return;
      // `apply` still runs, and still receives the authoritative result. The
      // streamed text was only a preview: dropping the placeholder here and
      // letting `apply` append the real turn keeps one code path responsible for
      // what ends up in the transcript, whether or not any tokens arrived.
      dropStreamingPlaceholder();
      apply(result);
    } catch (error) {
      if (onScreenRef.current !== sid) return;
      dropStreamingPlaceholder();
      failed(error);
    } finally {
      setBusy(false);
    }
  };

  /** Attach a report: read it server-side and add it to this user's library. */
  const attach = async (files: FileList | null) => {
    if (!files?.length) return;
    if (!token) {
      toast.error("Please log in to attach a report.");
      return;
    }
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const result = await uploadDocument(file, token);
        if (result.indexed > 0) {
          setDocuments((current) =>
            current.includes(result.filename)
              ? current
              : [...current, result.filename],
          );
          toast.success(`${result.filename} added. You can ask about it now.`);
        } else {
          // Almost always a scan with no OCR available. Say so, rather than
          // showing it as attached and letting them wonder why questions about
          // it get nothing.
          toast.error(
            `Couldn't read ${result.filename}. If it's a scan, try a clearer photo or a PDF with selectable text.`,
          );
        }
      }
    } catch (error) {
      toast.error(
        error instanceof ConsultUnavailableError
          ? error.message
          : "Upload failed.",
      );
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const empty = turns.length === 0;

  /**
   * Is the reply already on screen?
   *
   * `busy` stays true for the whole request and the loader renders after every
   * turn, so from the first token until `done` the reader would otherwise see
   * the answer growing with its caret AND a loader underneath insisting nothing
   * had started.
   *
   * No new state: a streaming reply is by construction the LAST turn with
   * `streaming` set, the same invariant `streamToken` and
   * `dropStreamingPlaceholder` are built on. Derived here, it cannot drift out
   * of step with them.
   *
   * Deliberately NOT "busy for more than N ms". Several paths return no tokens
   * at all — the mock provider, and every `postConsult` fallback inside
   * `postConsultStream` (fetch failure, non-2xx, a stream that dies before
   * `done`). Those wait out the whole turn in silence and must keep the dots.
   */
  const lastTurn = turns[turns.length - 1];
  const answerArriving =
    lastTurn?.who === "bot" && "streaming" in lastTurn && lastTurn.streaming === true;

  return (
    // `dvh` rather than `vh`: on mobile browsers the toolbar collapses as you
    // scroll and `vh` does not follow, which left the composer under the chrome.
    // min-h-0 on the scroller is what actually lets a flex child scroll instead
    // of growing the page — without it the composer is pushed off-screen.
    // The subtraction has to match the chrome ABOVE this screen, and there is a
    // different amount of it on each breakpoint:
    //
    //   mobile   sidebar's own bar (h-14, md:hidden) + Topbar (h-14) = 7rem
    //   md and up  the bar is hidden, so just the Topbar             = 3.5rem
    //
    // Both Topbar figures moved from 3rem when it went h-12 -> h-14 to line up
    // with the sidebar header and the mobile bar, which are both h-14; the two
    // horizontal rules meeting at the sidebar edge did not previously align.
    // If the Topbar height changes again, THESE TWO NUMBERS MUST CHANGE WITH IT.
    //
    // It subtracted a flat 3.5rem, which is neither. On mobile that made the
    // screen 48px taller than the space it had, and since this container is
    // overflow-hidden the composer went under the fold with no way to scroll to
    // it — the message box was simply unreachable on a phone.
    <div className="relative h-[calc(100dvh-7rem)] w-full overflow-hidden bg-background md:h-[calc(100dvh-3.5rem)]">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="relative mx-auto flex h-full w-full max-w-3xl flex-col px-3 sm:px-5">
        <div
          ref={scrollRef}
          // The transcript announces itself. Without this a screen-reader user
          // was told nothing at all when a reply arrived — on a chat surface
          // that is not a rough edge, it is the product not existing for them.
          //
          // `additions` rather than the default `additions text` on purpose:
          // streamed tokens are written into the SAME text node, which is a text
          // mutation, so the default would read the answer out again on every
          // chunk. Restricting it to additions means each turn is announced once
          // when it appears.
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Conversation"
          // On an empty chat the greeting is centred rather than pinned to the
          // top, which otherwise left a screen-height void between it and the
          // composer and made the page look half-loaded. `justify-center` only
          // applies while empty; once a conversation starts it goes back to
          // normal top-down flow so messages do not jump around.
          className={`mt-4 flex min-h-0 flex-1 flex-col space-y-5 overflow-y-auto scroll-smooth pb-6 pr-1 sm:space-y-6 ${
            empty ? "justify-center" : ""
          }`}
        >
          {/* The assistant speaks first, and asks nothing yet.
              Options only ever appear once the user has said what's wrong  -  the
              whole point is that they're chosen for that specific problem, so
              offering any before then would just be guessing. */}
          {empty && (
            <div className="animate-rise-in">
              <BotBubble>
                <div className="rounded-2xl rounded-tl-md border border-border bg-card p-4 elev-1">
                  <p className="font-display text-base font-semibold text-foreground">
                    Namaste
                  </p>
                  <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">
                    Tell me what&apos;s troubling you — one line is enough, in English,
                    Hindi or Hinglish. I&apos;ll ask a few questions you can tap through,
                    then build a plan from the Ayurveda notes and show you which ones
                    it came from.
                  </p>

                  {/* STARTERS, not a second paragraph explaining the first.
                      A blank chat asks the reader to compose an opening line
                      before they know what this thing can do, which is the
                      moment most people close the tab. These are the four most
                      common complaints in the knowledge base, in the language
                      people actually type — the `aliases` in the notes
                      themselves are written the same way. */}
                  <div className="mt-3.5 flex flex-wrap gap-1.5">
                    {STARTERS.map((starter) => (
                      <button
                        key={starter}
                        type="button"
                        onClick={() => send(starter)}
                        disabled={busy}
                        className="rounded-full border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-brand/40 hover:bg-brand-soft hover:text-brand disabled:opacity-50"
                      >
                        {starter}
                      </button>
                    ))}
                  </div>
                </div>
              </BotBubble>
            </div>
          )}

          {turns.map((turn) =>
            turn.who === "user" ? (
              <div
                key={turn.id}
                // `break-words` is not decoration: a pasted URL or a long
                // unbroken word would otherwise widen the bubble past the
                // viewport and give the whole page a horizontal scrollbar.
                className="ml-auto max-w-[85%] animate-rise-in whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm font-medium leading-relaxed text-brand-foreground elev-2 sm:max-w-[78%]"
              >
                {turn.text}
              </div>
            ) : turn.kind === "error" ? (
              // A service failure, not a reply. Deliberately NOT in a chat bubble:
              // it isn't something the assistant said, and dressing it up as one
              // makes users reword their message instead of waiting.
              <div
                key={turn.id}
                role="alert"
                className="animate-rise-in flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/5 p-3.5 text-sm text-destructive elev-1"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0">
                  {/* An expired login used to be announced as "AI service
                      unavailable (401)", which points the reader at the wrong
                      thing entirely: the AI is fine, their session is not, and
                      waiting — the reasonable response to an outage — never
                      fixes it. */}
                  <p className="font-semibold">
                    {turn.reason === "signed_out"
                      ? "You have been signed out"
                      : turn.reason === "session"
                        ? "Your session expired"
                        : "AI service unavailable"}
                  </p>
                  <p className="mt-0.5 leading-relaxed">{turn.text.replace(/^s️\s*/, "")}</p>
                  {/* Two different failures, two different remedies. A stale
                      token is fixed by reloading; a session whose refresh has
                      failed is over, and reloading only bounces the reader to
                      the login page without telling them why. */}
                  {turn.reason === "signed_out" ? (
                    <a
                      href={`/login?redirect=${encodeURIComponent("/consult")}`}
                      className="mt-2 inline-block rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground transition hover:brightness-110"
                    >
                      Sign in again
                    </a>
                  ) : turn.reason === "session" ? (
                    <button
                      type="button"
                      onClick={() => window.location.reload()}
                      className="mt-2 rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground transition hover:brightness-110"
                    >
                      Refresh page
                    </button>
                  ) : null}
                </div>
              </div>
            ) : (
              <BotBubble key={turn.id}>
                <div className="rounded-2xl rounded-tl-md border border-border bg-card p-3.5 elev-1">
                  {turn.kind === "escalation" ? (
                    <div className="flex gap-2 text-sm text-destructive">
                      <ShieldAlert className="h-5 w-5 shrink-0" />
                      <p className="whitespace-pre-wrap">{turn.text}</p>
                    </div>
                  ) : turn.kind === "chat" ? (
                    // Conversational replies are prose, not a sectioned plan, so
                    // they render as plain paragraphs.
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-secondary">
                      {turn.text}
                    </p>
                  ) : "streaming" in turn && turn.streaming ? (
                    // Still arriving. Rendered as plain prose with a caret
                    // rather than through AnswerSections, because a half-written
                    // answer has no complete section headings to split on yet
                    // and would flicker between layouts as they appeared.
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-secondary">
                      {turn.text}
                      <span
                        aria-hidden
                        className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-soft-pulse bg-brand"
                      />
                    </p>
                  ) : (
                    <AnswerSections text={turn.text} />
                  )}
                  {/* CITATIONS ARE NOT SHOWN. The backend still returns `sources`
                      and the transcript still persists them, so restoring this is
                      one import plus one line — but nothing in the UI reveals
                      which notes an answer was built from. `answer-sources.tsx`
                      stays on disk, unreferenced. */}
                </div>
              </BotBubble>
            ),
          )}

          {/* THREE DOTS, AND NO WORDS — and they step aside the moment there
              is something to read. `busy` stays true for the whole request, so
              without `answerArriving` this would sit beneath an answer that is
              visibly streaming and claim it had not started.

              This block used to narrate: a growing Hinglish checklist on
              elapsed-time thresholds ("Samajh raha hoon…" -> "Notes dhoond raha
              hoon…" -> "…plan bana raha hoon…"), spinner on the live line, tick
              on the finished ones. Removed by decision, and the argument for it
              is not a reason to bring it back. That argument was: turns took
              ~17-18s, and seventeen seconds of dots read as broken, so people
              reload and abandon a request that was about to succeed. Measured
              again after the move to Ollima: 2.5s for an opening complaint,
              7.0s worst case, first token at ~5.5s on the turns that stream.
              The wait it was written for no longer exists.

              If narration is ever wanted back, it has to come from real progress
              events on the SSE channel — which carries only `token`, `done` and
              `error` today — rather than from a clock that guesses, and it has
              to go through i18n rather than hardcoded literals on a `[locale]`
              route. */}
          {busy && !answerArriving && (
            <BotBubble>
              <div className="inline-flex items-center rounded-2xl rounded-tl-md border border-border bg-card px-4 py-3 elev-1">
                {/* The surrounding log announces this once when it appears. No
                    nested live region — that would read it twice. The dots are
                    aria-hidden, so this line is the ONLY thing a screen reader
                    gets while a request is in flight. */}
                <span className="sr-only">Preparing your answer</span>
                {/* `animate-soft-pulse`, the same breath as the streaming caret
                    above, NOT a bounce: it is the one animation globals.css
                    switches off BY NAME under prefers-reduced-motion, and it
                    fades instead of translating, which is what that block says
                    matters. Reduced motion leaves three static brand dots. */}
                <span aria-hidden className="flex items-center gap-1.5">
                  {[0, 200, 400].map((delay) => (
                    <span
                      key={delay}
                      className="h-2 w-2 animate-soft-pulse rounded-full bg-brand"
                      style={{ animationDelay: `${delay}ms` }}
                    />
                  ))}
                </span>
              </div>
            </BotBubble>
          )}
        </div>

        {/* Composer  -  typing stays available throughout, but is never required. */}
        <div className="pb-5">
          {documents.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {documents.map((name) => (
                <span
                  key={name}
                  className="flex items-center gap-1.5 rounded-lg bg-brand-soft px-2 py-1 text-2xs text-brand"
                >
                  <FileText className="h-3 w-3" />
                  {name}
                </span>
              ))}
              <span className="text-2xs text-text-secondary">
                — ask me anything about these
              </span>
            </div>
          )}

          {/* The composer sits on the card surface rather than translucent
              white, so it reads as one solid object over the page wash instead
              of a pane of frosted glass. pb + safe-area keeps it clear of the
              home indicator on modern phones. */}
          <div className="mb-[max(0.75rem,env(safe-area-inset-bottom))] flex items-end gap-1.5 rounded-2xl border border-border bg-card/95 p-2 elev-2 backdrop-blur-sm transition-all duration-200 focus-within:border-brand/60 focus-within:ring-4 focus-within:ring-brand/10 sm:gap-2">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp"
              onChange={(e) => attach(e.target.files)}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={uploading || busy}
              title="Attach a report (PDF, photo or text)"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-text-secondary transition hover:bg-surface-2 hover:text-foreground disabled:opacity-40"
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </button>
            <textarea
              ref={composerRef}
              aria-label="Your message"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              // Kept short deliberately. The longer wording wrapped onto a
              // second line inside a one-row textarea at 390px and was clipped
              // by the bottom edge, so on a phone the hint was unreadable.
              placeholder={
                IN_CONSULTATION.has(context?.phase ?? "idle")
                  ? "Add anything else (optional)…"
                  : "Describe what's troubling you…"
              }
              // 16px on small screens is not a style choice: iOS Safari zooms
              // the whole page when a focused input is smaller than that, and
              // the zoom does not undo itself.
              className="max-h-40 flex-1 resize-none bg-transparent p-2 text-base leading-relaxed text-foreground outline-none placeholder:text-text-secondary sm:text-sm"
            />
            <button
              type="button"
              // `detail === 0` means the click came from Enter or Space on the
              // button rather than a pointer — the one case where focus needs
              // putting back in the composer. See `send`.
              onClick={(e) => send(input, e.detail === 0)}
              disabled={busy || !input.trim()}
              aria-label="Send"
              // 44px minimum on touch: below that it is measurably harder to hit.
              className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground elev-2 transition-all duration-200 hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:shadow-none sm:h-10 sm:w-10"
            >
              {/* idle → sending. A send button that looks identical before and
                  after the tap invites a second tap, and on a 17-second request
                  that is a second billed consultation. */}
              {busy ? (
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
              ) : (
                <SendHorizonal aria-hidden className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="mt-2 text-center text-2xs text-text-secondary">
            Educational wellness guidance only · Ayurveda &amp; Yoga · by Ollasoftware
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ConsultPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-text-secondary">Loading…</div>}>
      <ConsultInner />
    </Suspense>
  );
}
