"use client";

import { cn } from "@v1/ui/utils";
import { ArrowUp, Square, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { describeCode } from "@/lib/api/errors";
import { MESSAGE_MAX } from "@/lib/api/types";
import { useChatEntry, useStores } from "./chat-context";
import { shouldSubmit } from "./keyboard";

const MAX_HEIGHT_PX = 200;
/** Show the character counter this close to the limit. */
const COUNTER_FROM = MESSAGE_MAX - 1000;

/**
 * The message box.
 *
 *   - grows with its text up to a limit, then scrolls
 *   - Enter sends, Shift+Enter adds a line; Enter while an IME is composing does not
 *     send (see keyboard.ts)
 *   - while THIS chat is streaming, Send becomes Stop; other chats are unaffected
 *   - a send the server refused (busy, rate-limited, too long, offline) puts the
 *     text back here with the reason above it — nothing typed is lost
 *   - 16 px text on phones: iOS zooms the page when a focused field is smaller
 */
export function Composer({ chatKey, onSent }: { chatKey: string; onSent?: () => void }) {
  const { chat } = useStores();
  const entry = useChatEntry(chatKey);
  const [value, setValue] = useState(() => chat.getDraft(chatKey));
  const textarea = useRef<HTMLTextAreaElement>(null);

  const stream = entry?.stream ?? null;
  const tooLong = value.length > MESSAGE_MAX;
  const canSend = Boolean(value.trim()) && !stream && !tooLong;
  const error = entry?.composerError ?? null;

  // Each conversation keeps its own unsent text.
  useEffect(() => {
    setValue(chat.getDraft(chatKey));
    // Focus on arrival where a physical keyboard is likely (not on touch, where it
    // would pop the on-screen keyboard over the conversation).
    if (window.matchMedia?.("(pointer: fine)").matches) textarea.current?.focus();
  }, [chat, chatKey]);

  // A refused send put the text back in the draft; show it again.
  useEffect(() => {
    if (error) setValue(chat.getDraft(chatKey));
  }, [error, chat, chatKey]);

  useLayoutEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`;
    element.style.overflowY = element.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
  }, [value]);

  const send = () => {
    if (!canSend) return;
    const text = value;
    setValue("");
    chat.setDraft(chatKey, "");
    onSent?.();
    void chat.send(chatKey, text);
  };

  const stop = () => void chat.stop(chatKey);

  return (
    <div className="shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-5">
      <div className="mx-auto w-full max-w-3xl">
        {error && (
          <div
            role="alert"
            className="mb-2 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            <p className="min-w-0 flex-1">
              <span className="font-semibold">{describeCode(error.code).title}.</span>{" "}
              {describeCode(error.code).message}
            </p>
            <button
              type="button"
              onClick={() => chat.clearComposerError(chatKey)}
              className="focus-ring -mr-1 grid h-6 w-6 shrink-0 place-items-center rounded-md hover:bg-destructive/10"
              aria-label="Dismiss"
            >
              <X aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <form
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
          className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 elev-2 transition-colors focus-within:border-brand/60 focus-within:ring-4 focus-within:ring-brand/10"
        >
          <label htmlFor={`composer-${chatKey}`} className="sr-only">
            Message
          </label>
          <textarea
            id={`composer-${chatKey}`}
            ref={textarea}
            rows={1}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              chat.setDraft(chatKey, event.target.value);
              if (error) chat.clearComposerError(chatKey);
            }}
            onKeyDown={(event) => {
              if (shouldSubmit(event)) {
                event.preventDefault();
                send();
              }
            }}
            placeholder="Message the assistant…"
            aria-describedby={`composer-hint-${chatKey}`}
            aria-invalid={tooLong || undefined}
            className="max-h-[200px] min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-base leading-relaxed text-foreground outline-none placeholder:text-text-secondary sm:text-[0.9375rem]"
          />
          {stream ? (
            <button
              type="button"
              onClick={stop}
              disabled={stream.phase !== "streaming"}
              aria-label={stream.phase === "stopping" ? "Stopping" : "Stop generating"}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-foreground text-background transition hover:brightness-110 disabled:opacity-50 sm:h-10 sm:w-10"
            >
              <Square aria-hidden className="h-3.5 w-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              aria-label="Send message"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground elev-1 transition hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 sm:h-10 sm:w-10"
            >
              <ArrowUp aria-hidden className="h-4 w-4" />
            </button>
          )}
        </form>

        <div
          id={`composer-hint-${chatKey}`}
          className="mt-1.5 flex items-center justify-between gap-3 px-1 text-2xs text-text-secondary"
        >
          <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line</span>
          <span className="sm:hidden">AI can make mistakes.</span>
          {value.length > COUNTER_FROM ? (
            <span className={cn("tabular-nums", tooLong && "font-semibold text-destructive")}>
              {value.length.toLocaleString()} / {MESSAGE_MAX.toLocaleString()}
            </span>
          ) : (
            <span className="hidden sm:inline">AI can make mistakes. Check important information.</span>
          )}
        </div>
      </div>
    </div>
  );
}
