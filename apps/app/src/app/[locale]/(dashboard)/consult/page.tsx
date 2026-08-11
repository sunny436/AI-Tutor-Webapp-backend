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
  Mic,
  Paperclip,
  SendHorizonal,
  ShieldAlert,
  Square,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ConsultUnavailableError,
  postConsult,
  postConsultStream,
  transcribeAudio,
  uploadDocument,
} from "@/lib/consult/client";
import { useVoiceRecorder } from "@/lib/consult/use-voice";
import { CONSULTING, answeredCount } from "@/lib/consult/types";
import type {
  ConsultContext,
  ConsultResult,
  IntakePlan,
  PersistedConsultState,
  Selection,
} from "@/lib/consult/types";
import { AnswerSections } from "./_components/answer-sections";
import { IntakePanel } from "./_components/intake-panel";
import { SpeakButton } from "./_components/speak-button";

type Turn =
  | { who: "user"; text: string }
  | {
      who: "bot";
      kind: "chat" | "answer" | "escalation" | "error";
      text: string;
      /** True while tokens are still arriving, so the bubble can show it. */
      streaming?: boolean;
    }
  | { who: "bot"; kind: "intake"; plan: IntakePlan; selection?: Selection; locked: boolean };

/** Phases where a typed message is extra detail rather than a new message. */
const IN_CONSULTATION = new Set<string>(CONSULTING);

function newId() {
  try {
    return crypto.randomUUID();
  } catch {
    return `s_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  }
}

function BotBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex max-w-[94%] gap-2.5">
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-sm">
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
  const voice = useVoiceRecorder();

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  /**
   * Rehydrate a saved chat. The transcript alone is not enough  -  without the
   * persisted `state` the next message would restart the consultation from
   * scratch, which is exactly what the old page did.
   */
  const loadedRef = useRef<string | null>(null);
  useEffect(() => {
    const key = urlSession ?? "new";
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
        restored.push({ who: "user", text: message.content });
        continue;
      }
      let state: PersistedConsultState | null = null;
      try {
        state = message.state ? (JSON.parse(message.state) as PersistedConsultState) : null;
      } catch {
        state = null; // an unreadable blob just means "no resume", never a crash
      }
      if (state?.context) lastContext = state.context;

      if (message.kind === "intake" && state?.intake) {
        restored.push({
          who: "bot",
          kind: "intake",
          plan: state.intake,
          selection: state.context?.answers,
          // Only the newest card set stays interactive.
          locked: true,
        });
      } else {
        const kind =
          message.kind === "escalation" || message.kind === "chat"
            ? (message.kind as "escalation" | "chat")
            : "answer";
        restored.push({ who: "bot", kind, text: message.content });
      }
    }

    // Reopen the last card set if the consultation was left mid-intake.
    const last = restored[restored.length - 1];
    if (
      last &&
      last.who === "bot" &&
      last.kind === "intake" &&
      IN_CONSULTATION.has(lastContext?.phase ?? "")
    ) {
      last.locked = false;
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
      // A new card set supersedes the previous one, so only one is ever live.
      const locked = current.map((turn) =>
        turn.who === "bot" && turn.kind === "intake" ? { ...turn, locked: true } : turn,
      );
      if (result.kind === "intake" && result.intake) {
        return [
          ...locked,
          { who: "bot", kind: "intake", plan: result.intake, locked: false },
        ];
      }
      const kind =
        result.kind === "escalation" || result.kind === "chat" || result.kind === "error"
          ? result.kind
          : "answer";
      return [...locked, { who: "bot", kind, text: result.answer }];
    });
  }, []);

  const failed = (error: unknown) => {
    const message =
      error instanceof ConsultUnavailableError
        ? error.message
        : "Something went wrong. Please try again.";
    toast.error(message);
    // Same reasoning as the server-reported outage above: this is a failure, not
    // a reply, so it gets the warning banner rather than a chat bubble.
    setTurns((current) => [...current, { who: "bot", kind: "error", text: message }]);
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
        return [...current.slice(0, -1), { ...last, text: last.text + piece }];
      }
      return [...current, { who: "bot", kind: "answer", text: piece, streaming: true }];
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

  /** Start (or restart) a consultation from a typed sentence. */
  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    setInput("");

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
      setSessionId(sid);
      // Put the session in the URL so a refresh keeps the chat and the sidebar
      // can highlight it.
      window.history.replaceState({}, "", `?c=${sid}`);
    }

    setTurns((current) => [...current, { who: "user", text }]);
    saveMsg({ sessionId: sid, role: "user", content: text }).catch(() => {});

    // Typing during a consultation is extra detail; otherwise the message gets
    // routed. Either way the context MUST go along  -  it carries the conversation
    // memory, and without it every message looked like the first one, so the
    // assistant kept re-greeting and re-asking what was wrong.
    const inConsultation = IN_CONSULTATION.has(context?.phase ?? "idle");
    setBusy(true);
    try {
      const result = await postConsultStream(
        inConsultation ? { context, freeText: text } : { problem: text, context },
        streamToken,
        undefined,
        token,
      );
      // `apply` still runs, and still receives the authoritative result. The
      // streamed text was only a preview: dropping the placeholder here and
      // letting `apply` append the real turn keeps one code path responsible for
      // what ends up in the transcript, whether or not any tokens arrived.
      dropStreamingPlaceholder();
      apply(result);
      persist(sid, result);
    } catch (error) {
      dropStreamingPlaceholder();
      failed(error);
    } finally {
      setBusy(false);
    }
  };

  /** Submit a set of tapped answers. */
  const submitIntake = async (selection: Selection) => {
    if (busy || !context) return;
    const sid = sessionId ?? newId();
    if (!sessionId) {
      // Same claim as in `send` — a session this tab just minted must not be
      // rehydrated out from under itself.
      loadedRef.current = sid;
      setSessionId(sid);
    }

    setBusy(true);
    try {
      const result = await postConsult(
        { context, answers: selection },
        undefined,
        token,
      );
      apply(result);
      persist(sid, result);
    } catch (error) {
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

  /** Record, transcribe, and put the text in the box - never send it blind. */
  const toggleMic = async () => {
    if (voice.state === "recording") {
      const clip = await voice.stop();
      if (!clip) return;
      try {
        const { text } = await transcribeAudio(clip, token);
        if (!text) {
          toast.error("Didn't catch that. Try again?");
          return;
        }
        // Into the box, not straight to the backend. A mis-heard sentence should
        // cost one edit, not one wrong consultation.
        setInput((current) => (current ? `${current} ${text}` : text));
      } catch {
        toast.error("Could not transcribe that.");
      }
      return;
    }
    await voice.start();
  };

  useEffect(() => {
    if (voice.error) toast.error(voice.error);
  }, [voice.error]);

  const empty = turns.length === 0;

  return (
    <div className="h-[calc(100vh-3rem)] w-full overflow-hidden bg-gradient-to-br from-emerald-50 via-white to-teal-50 dark:from-zinc-950 dark:via-black dark:to-emerald-950/30">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4">
        <div ref={scrollRef} className="mt-4 flex-1 space-y-4 overflow-y-auto pb-4 pr-1">
          {/* The assistant speaks first, and asks nothing yet.
              Options only ever appear once the user has said what's wrong  -  the
              whole point is that they're chosen for that specific problem, so
              offering any before then would just be guessing. */}
          {empty && (
            <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
              <BotBubble>
                <div className="rounded-2xl rounded-tl-md border border-border bg-white/80 p-4 shadow-sm backdrop-blur dark:bg-white/[0.04]">
                  <p className="text-sm font-semibold text-primary">Namaste 🌿</p>
                  <p className="mt-1.5 text-sm leading-relaxed text-primary/75">
                    I&apos;m your Ayurveda &amp; Yoga wellness assistant. Tell me what&apos;s
                    troubling you  -  one line is enough.
                  </p>
                  <p className="mt-2.5 text-sm leading-relaxed text-primary/75">
                    I&apos;ll then ask a few quick questions you can simply tap through, and give
                    you the likely root cause, a food chart, yoga &amp; breathing, and a daily
                    routine.
                  </p>
                  <p className="mt-3 text-xs text-primary/45">
                    For example: <span className="italic">&ldquo;I have had acidity for a week&rdquo;</span>
                  </p>
                </div>
              </BotBubble>
            </div>
          )}

          {turns.map((turn, i) =>
            turn.who === "user" ? (
              <div
                key={i}
                className="ml-auto max-w-[80%] rounded-2xl rounded-tr-md bg-gradient-to-br from-emerald-500 to-teal-600 px-4 py-2.5 text-sm font-medium text-white shadow-md shadow-emerald-500/20"
              >
                {turn.text}
              </div>
            ) : turn.kind === "intake" ? (
              <BotBubble key={i}>
                {turn.locked ? (
                  <div className="rounded-2xl border border-border bg-white/60 p-3.5 text-sm text-primary/60 dark:bg-white/[0.03]">
                    <span className="font-medium text-primary/75">
                      {turn.plan.condition || "Your answers"}
                    </span>{" "}
                    {/* Count what was ACTUALLY answered. This printed
                        "N questions answered o"" unconditionally, so a card set
                        the user never touched  -  because they typed a new message
                        instead of tapping  -  still claimed all N were answered. */}
                    {(() => {
                      const total = turn.plan.questions.length;
                      const done = answeredCount(turn.plan.questions, turn.selection ?? {});
                      if (done === 0) return ` -  skipped, ${total} questions unanswered`;
                      return done === total
                        ? ` -  ${total} questions answered o"`
                        : ` -  ${done} of ${total} answered`;
                    })()}
                  </div>
                ) : (
                  <IntakePanel
                    plan={turn.plan}
                    initialSelection={turn.selection}
                    pending={busy}
                    onSubmit={submitIntake}
                  />
                )}
              </BotBubble>
            ) : turn.kind === "error" ? (
              // A service failure, not a reply. Deliberately NOT in a chat bubble:
              // it isn't something the assistant said, and dressing it up as one
              // makes users reword their message instead of waiting.
              <div
                key={i}
                role="alert"
                className="animate-in fade-in slide-in-from-bottom-1 flex items-start gap-2.5 rounded-xl border border-rose-500/40 bg-rose-50/80 p-3.5 text-sm text-rose-700 shadow-sm dark:bg-rose-500/10 dark:text-rose-300"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0">
                  <p className="font-semibold">AI service unavailable</p>
                  <p className="mt-0.5 leading-relaxed">{turn.text.replace(/^s️\s*/, "")}</p>
                </div>
              </div>
            ) : (
              <BotBubble key={i}>
                <div className="rounded-2xl rounded-tl-md border border-border bg-white/80 p-3.5 shadow-sm backdrop-blur dark:bg-white/[0.04]">
                  {turn.kind === "escalation" ? (
                    <div className="flex gap-2 text-sm text-rose-600 dark:text-rose-400">
                      <ShieldAlert className="h-5 w-5 shrink-0" />
                      <p className="whitespace-pre-wrap">{turn.text}</p>
                    </div>
                  ) : turn.kind === "chat" ? (
                    // Conversational replies are prose, not a sectioned plan, so
                    // they render as plain paragraphs.
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-primary/80">
                      {turn.text}
                    </p>
                  ) : "streaming" in turn && turn.streaming ? (
                    // Still arriving. Rendered as plain prose with a caret
                    // rather than through AnswerSections, because a half-written
                    // answer has no complete section headings to split on yet
                    // and would flicker between layouts as they appeared.
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-primary/80">
                      {turn.text}
                      <span
                        aria-hidden
                        className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-emerald-500/70"
                      />
                    </p>
                  ) : (
                    <AnswerSections text={turn.text} />
                  )}
                  {/* Error turns never reach here - they are filtered further
                      up - so there is no guard against reading "the backend is
                      unreachable" aloud. Hidden while streaming: there is
                      nothing complete to read out yet. */}
                  {!("streaming" in turn && turn.streaming) && <SpeakButton text={turn.text} />}
                </div>
              </BotBubble>
            ),
          )}

          {busy && (
            <div className="flex gap-2.5">
              <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-sm">
                <Leaf className="h-4 w-4" />
              </span>
              <div className="flex items-center gap-1 rounded-2xl rounded-tl-md border border-border bg-white/80 px-4 py-4 dark:bg-white/[0.04]">
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-500 [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-500 [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-500" />
              </div>
            </div>
          )}
        </div>

        {/* Composer  -  typing stays available throughout, but is never required. */}
        <div className="pb-5">
          {documents.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {documents.map((name) => (
                <span
                  key={name}
                  className="flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-700 dark:text-emerald-300"
                >
                  <FileText className="h-3 w-3" />
                  {name}
                </span>
              ))}
              <span className="text-[11px] text-primary/40">
                — ask me anything about these
              </span>
            </div>
          )}

          {voice.state === "recording" && (
            <div className="mb-2 flex items-center gap-2 rounded-lg bg-rose-500/10 px-3 py-1.5 text-[11px] text-rose-600 dark:text-rose-400">
              <span className="h-2 w-2 animate-pulse rounded-full bg-rose-500" />
              Listening… {voice.seconds}s
              <button
                type="button"
                onClick={voice.cancel}
                className="ml-auto underline hover:no-underline"
              >
                cancel
              </button>
            </div>
          )}

          <div className="flex items-end gap-2 rounded-2xl border border-border bg-white/80 p-2 shadow-lg shadow-emerald-500/5 backdrop-blur transition focus-within:border-emerald-500/50 focus-within:ring-2 focus-within:ring-emerald-500/15 dark:bg-white/[0.05]">
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
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-primary/50 transition hover:bg-primary/5 hover:text-primary disabled:opacity-40"
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder={
                IN_CONSULTATION.has(context?.phase ?? "idle")
                  ? "Add anything else (optional)..."
                  : "Ask me anything, or describe what's troubling you..."
              }
              className="max-h-32 flex-1 resize-none bg-transparent p-2 text-sm text-primary outline-none placeholder:text-primary/40"
            />
            <button
              type="button"
              onClick={toggleMic}
              disabled={busy || voice.state === "processing"}
              title={
                voice.state === "recording"
                  ? "Stop and transcribe"
                  : "Speak your question - any language"
              }
              className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl transition disabled:opacity-40 ${
                voice.state === "recording"
                  ? "bg-rose-500/15 text-rose-600 dark:text-rose-400"
                  : "text-primary/50 hover:bg-primary/5 hover:text-primary"
              }`}
            >
              {voice.state === "processing" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : voice.state === "recording" ? (
                <Square className="h-3.5 w-3.5 fill-current" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={() => send(input)}
              disabled={busy || !input.trim()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/25 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <SendHorizonal className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-primary/40">
            Educational wellness guidance only · Ayurveda &amp; Yoga · by Ollasoftware
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ConsultPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-primary/50">Loading...</div>}>
      <ConsultInner />
    </Suspense>
  );
}
