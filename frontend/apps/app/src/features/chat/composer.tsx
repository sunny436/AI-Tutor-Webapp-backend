"use client";

import { cn } from "@v1/ui/utils";
import { AudioLines, Mic, Paperclip, Send, Square, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { AttachmentChip } from "@/features/files/attachment-chip";
import { unlockAudio } from "@/features/voice/audio-unlock";
import { useVoiceOffered } from "@/features/voice/availability";
import { canSendDraft } from "@/features/files/attachment-store";
import { describeCode } from "@/lib/api/errors";
import { FILE_ACCEPT } from "@/lib/api/files";
import { ATTACHMENTS_MAX, MESSAGE_MAX } from "@/lib/api/types";
import { useAttachments, useChatEntry, useStores } from "./chat-context";
import { appendTranscript } from "./dictation";
import { shouldSubmit } from "./keyboard";
import { useDictation } from "./use-dictation";

const MAX_HEIGHT_PX = 200;
/** Show the character counter this close to the limit. */
const COUNTER_FROM = MESSAGE_MAX - 1000;

/**
 * The message box: [Attach] [text] [Mic] [Voice] [Send].
 *
 *   - grows with its text up to a limit, then scrolls
 *   - Enter sends, Shift+Enter adds a line; Enter while an IME is composing does not
 *     send (see keyboard.ts)
 *   - while THIS chat is streaming, Send becomes Stop; other chats are unaffected
 *   - a send the server refused (busy, rate-limited, too long, offline) puts the
 *     text (and its files) back here with the reason above it — nothing typed is lost
 *   - files (Attach, or dropped on the box) go to the File Library and show as chips; Send
 *     waits until every attached file is ready (the API refuses anything else too). Removing a
 *     chip only takes it off this message; the file stays in the library.
 *   - the mic types what the browser's speech recognition heard (final text only, added after
 *     the draft, never sent by itself); it is shown only where the browser can do it
 *   - Voice opens voice mode over this chat (features/voice): only where the API offers it and the
 *     browser can record and play; filled while the box is empty, quieter once Send has something
 *   - 16 px text on phones: iOS zooms the page when a focused field is smaller
 *   - no placeholder and no lines under it: its name ("Ask your doubt") and the keys are
 *     for assistive technology; only the character count shows, near the limit
 */
export function Composer({
  chatKey,
  onSent,
  onVoice,
}: {
  chatKey: string;
  onSent?: () => void;
  onVoice?: () => void;
}) {
  const { chat, attachments } = useStores();
  const voiceOffered = useVoiceOffered();
  const entry = useChatEntry(chatKey);
  const chips = useAttachments(chatKey);
  const [value, setValue] = useState(() => chat.getDraft(chatKey));
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dictation = useDictation((text) => {
    setValue((current) => {
      const next = appendTranscript(current, text);
      chat.setDraft(chatKey, next);
      return next;
    });
  });
  const abortDictation = dictation.abort;

  const stream = entry?.stream ?? null;
  // Send and Stop take each other's place with a quick scale-in, but not on the page's first
  // paint: only once the button has actually changed.
  const startedStreaming = useRef(Boolean(stream));
  const swapped = useRef(false);
  if (Boolean(stream) !== startedStreaming.current) swapped.current = true;
  const swapIn = swapped.current && "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-90 ease-enter";
  const tooLong = value.length > MESSAGE_MAX;
  const canSend = canSendDraft({ text: value, streaming: Boolean(stream), tooLong, chips });
  const error = entry?.composerError ?? null;
  const shownNotice = notice ?? dictation.error;

  // Each conversation keeps its own unsent text. A new chat getting its address (its draft key
  // becoming the conversation's id) is the same chat, not an arrival: it is left alone, so focus
  // is not pulled out of a menu the student has just opened (which would close it).
  const arrivedAt = useRef<string | null>(null);
  useEffect(() => {
    const previous = arrivedAt.current;
    arrivedAt.current = chatKey;
    if (previous !== null && chat.resolve(previous) === chat.resolve(chatKey)) return;
    abortDictation(); // words spoken for the previous chat never land in this one
    setNotice(null);
    setValue(chat.getDraft(chatKey));
    // Focus on arrival where a physical keyboard is likely (not on touch, where it
    // would pop the on-screen keyboard over the conversation).
    if (window.matchMedia?.("(pointer: fine)").matches) textarea.current?.focus();
  }, [chat, chatKey, abortDictation]);

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
    abortDictation();
    setValue("");
    setNotice(null);
    chat.setDraft(chatKey, "");
    const files = attachments.take(chatKey);
    onSent?.();
    void chat.send(chatKey, text, files);
  };

  const stop = () => void chat.stop(chatKey);

  const addFiles = (files: FileList | null) => {
    if (!files?.length) return;
    const { rejected } = attachments.add(chatKey, Array.from(files));
    const first = rejected[0];
    if (!first) return setNotice(null);
    const why =
      first.reason === "type"
        ? "isn't a supported file type (PDF, Word, PowerPoint, Excel, CSV, text or an image)"
        : first.reason === "size"
          ? "is too large (PDF, Word and PowerPoint up to 25 MB; Excel and images 10 MB; text 2 MB)"
          : `wasn't added: up to ${ATTACHMENTS_MAX} files per message`;
    setNotice(`${first.name} ${why}.${rejected.length > 1 ? ` ${rejected.length - 1} more not added.` : ""}`);
  };

  return (
    <div className="scrollbar-subtle shrink-0 overflow-hidden bg-background pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 [scrollbar-gutter:stable]">
      {/* The chat column (message-list.tsx): the side padding is inside it, and the same scrollbar
          gutter as the transcript is reserved above, so the composer's edges match the messages'. */}
      <div className="mx-auto w-full px-5 sm:px-6 lg:w-[min(100%,clamp(42.5rem,75%,57rem))]">
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
        {shownNotice && (
          <div
            role="status"
            className="mb-2 flex items-start gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground"
          >
            <p className="min-w-0 flex-1">{shownNotice}</p>
            <button
              type="button"
              onClick={() => {
                setNotice(null);
                dictation.clearError();
              }}
              className="focus-ring -mr-1 grid h-6 w-6 shrink-0 place-items-center rounded-md hover:bg-card"
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
          onDragOver={(event) => {
            if (!Array.from(event.dataTransfer.types).includes("Files")) return;
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            if (!event.dataTransfer.files.length) return;
            event.preventDefault();
            setDragging(false);
            addFiles(event.dataTransfer.files);
          }}
          className={cn(
            "elev-1 flex flex-col gap-1.5 rounded-[1.25rem] border border-border bg-card p-2 transition-[border-color,box-shadow] focus-within:border-brand/50 focus-within:ring-2 focus-within:ring-brand/15",
            dragging && "border-brand/60 ring-2 ring-brand/25",
          )}
        >
          {chips.length > 0 && (
            <div className="scrollbar-subtle flex gap-1.5 overflow-x-auto px-1 pb-0.5" role="group" aria-label="Attached files">
              {chips.map((chip) => (
                <AttachmentChip
                  key={chip.localId}
                  chip={chip}
                  onRemove={() => attachments.remove(chatKey, chip.localId)}
                  onRetry={() => void attachments.retry(chatKey, chip.localId)}
                />
              ))}
            </div>
          )}
          <div className="flex items-end gap-1.5">
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              aria-label="Attach files"
              title="Attach files (PDF, Word, PowerPoint, Excel, CSV, text, images)"
              className="focus-ring grid h-11 w-11 shrink-0 place-items-center rounded-xl text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground sm:h-10 sm:w-10"
            >
              <Paperclip aria-hidden className="h-5 w-5" />
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={FILE_ACCEPT}
              hidden
              onChange={(event) => {
                addFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <label htmlFor={`composer-${chatKey}`} className="sr-only">
              Ask your doubt
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
              aria-describedby={`composer-hint-${chatKey}`}
              aria-invalid={tooLong || undefined}
              className="max-h-[200px] min-h-[2.75rem] min-w-0 flex-1 resize-none bg-transparent px-2 py-2.5 text-base font-normal leading-normal text-foreground outline-none"
            />
            {dictation.supported && (
              <button
                type="button"
                onClick={dictation.toggle}
                disabled={dictation.state === "stopping"}
                aria-pressed={dictation.state !== "idle"}
                aria-label="Dictate"
                title={dictation.state === "idle" ? "Dictate" : "Stop dictation"}
                className={cn(
                  "focus-ring grid h-11 w-11 shrink-0 place-items-center rounded-xl transition-colors disabled:opacity-60 sm:h-10 sm:w-10",
                  dictation.state === "idle"
                    ? "text-text-secondary hover:bg-surface-2 hover:text-foreground"
                    : "bg-brand-soft text-brand",
                )}
              >
                <Mic
                  aria-hidden
                  className={cn("h-5 w-5", dictation.state === "listening" && "motion-safe:animate-pulse")}
                />
              </button>
            )}
            {voiceOffered && onVoice && (
              <button
                type="button"
                onClick={() => {
                  unlockAudio(); // in the click itself: browsers only start sound from a gesture
                  abortDictation(); // one listener on the microphone at a time
                  onVoice();
                }}
                aria-label="Voice mode"
                title="Voice mode: talk with your tutor"
                className={cn(
                  "focus-ring grid h-11 w-11 shrink-0 place-items-center rounded-full transition-colors sm:h-10 sm:w-10",
                  value.trim()
                    ? "text-brand hover:bg-brand-soft"
                    : "elev-1 bg-brand text-brand-foreground hover:bg-brand-hover",
                )}
              >
                <AudioLines aria-hidden className="h-5 w-5" />
              </button>
            )}
            {stream ? (
              <button
                type="button"
                onClick={stop}
                disabled={stream.phase !== "streaming"}
                aria-label={stream.phase === "stopping" ? "Stopping" : "Stop generating"}
                className={cn(
                  "grid h-11 w-11 shrink-0 place-items-center rounded-full bg-foreground text-background transition hover:brightness-110 active:scale-[0.97] disabled:opacity-50 sm:h-10 sm:w-10",
                  swapIn,
                )}
              >
                <Square aria-hidden className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canSend}
                aria-label="Send message"
                className={cn(
                  "elev-1 grid h-11 w-11 shrink-0 place-items-center rounded-full bg-brand text-brand-foreground transition hover:bg-brand-hover active:scale-[0.97] disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-text-secondary disabled:shadow-none sm:h-10 sm:w-10",
                  swapIn,
                )}
              >
                <Send aria-hidden className="h-[18px] w-[18px]" />
              </button>
            )}
          </div>
        </form>

        <div id={`composer-hint-${chatKey}`} className="flex justify-end px-3 text-2xs text-text-secondary">
          <span className="sr-only">
            Enter to send, Shift + Enter for a new line.
            {chips.some((chip) => chip.state !== "ready") ? " Send waits until every attached file is ready." : ""}
          </span>
          {value.length > COUNTER_FROM && (
            <span className={cn("mt-1.5 shrink-0 tabular-nums", tooLong && "font-semibold text-destructive")}>
              {value.length.toLocaleString()} / {MESSAGE_MAX.toLocaleString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
