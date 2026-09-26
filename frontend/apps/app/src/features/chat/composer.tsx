"use client";

import { cn } from "@v1/ui/utils";
import { Mic, Paperclip, Send, Square, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { PreviewBadge } from "@/components/preview-badge";
import { usePreview } from "@/components/preview-context";
import { describeCode } from "@/lib/api/errors";
import { APP_NAME } from "@/lib/brand";
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
 *   - attach and voice exist only as preview UI (lib/preview.ts): disabled and
 *     marked "Soon", and absent in production
 */

/** An icon button that does nothing yet: disabled, named as such, marked "Soon". */
function SoonButton({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled
      aria-label={`${label} (coming soon)`}
      className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl text-text-secondary disabled:cursor-not-allowed sm:h-10 sm:w-10"
    >
      {children}
      <PreviewBadge label="Soon" className="absolute -right-1 -top-1.5 px-1 text-[0.5625rem] leading-3" />
    </button>
  );
}

export function Composer({ chatKey, onSent }: { chatKey: string; onSent?: () => void }) {
  const { chat } = useStores();
  const preview = usePreview();
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
    <div className="shrink-0 bg-background px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-5">
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
          className="flex items-end gap-1.5 rounded-3xl border border-border bg-card p-2 shadow-sm transition-colors focus-within:border-brand/60 focus-within:ring-2 focus-within:ring-brand/15"
        >
          {preview && (
            <SoonButton label="Attach an image or PDF">
              <Paperclip aria-hidden className="h-5 w-5" />
            </SoonButton>
          )}
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
            placeholder="Ask your doubt in English or Hinglish (e.g. 'Explain Newton's laws' or 'solve x² + 5x + 6 = 0')…"
            aria-describedby={`composer-hint-${chatKey}`}
            aria-invalid={tooLong || undefined}
            className="max-h-[200px] min-h-[2.75rem] min-w-0 flex-1 resize-none bg-transparent px-2 py-2.5 text-base leading-relaxed text-foreground outline-none placeholder:truncate placeholder:text-text-secondary sm:text-sm"
          />
          {preview && (
            <SoonButton label="Voice input">
              <Mic aria-hidden className="h-5 w-5" />
            </SoonButton>
          )}
          {stream ? (
            <button
              type="button"
              onClick={stop}
              disabled={stream.phase !== "streaming"}
              aria-label={stream.phase === "stopping" ? "Stopping" : "Stop generating"}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-foreground text-background transition hover:brightness-110 disabled:opacity-50 sm:h-10 sm:w-10"
            >
              <Square aria-hidden className="h-3.5 w-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              aria-label="Send message"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-brand text-brand-foreground transition hover:bg-brand-hover active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 sm:h-10 sm:w-10"
            >
              <Send aria-hidden className="h-[18px] w-[18px]" />
            </button>
          )}
        </form>

        <div
          id={`composer-hint-${chatKey}`}
          className="mt-1.5 flex items-center justify-between gap-3 px-3 text-2xs text-text-secondary"
        >
          <span className="flex min-w-0 items-center gap-1">
            <span className="truncate">
              Powered by {APP_NAME} · AI can make mistakes<span className="hidden sm:inline">. Check important answers</span>.
            </span>
          </span>
          {value.length > COUNTER_FROM ? (
            <span className={cn("shrink-0 tabular-nums", tooLong && "font-semibold text-destructive")}>
              {value.length.toLocaleString()} / {MESSAGE_MAX.toLocaleString()}
            </span>
          ) : (
            <span className="hidden shrink-0 sm:inline">Enter to send · Shift + Enter for a new line</span>
          )}
        </div>
      </div>
    </div>
  );
}
