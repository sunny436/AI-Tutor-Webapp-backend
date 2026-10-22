"use client";

import { cn } from "@v1/ui/utils";
import { Check, Copy, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { describeError } from "@/lib/api/errors";
import type { FeedbackRating } from "@/lib/api/types";
import type { ChatMessage } from "./chat-store";
import { useStores } from "./chat-context";

const actionClass =
  "focus-ring grid h-8 w-8 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

/**
 * Copy, regenerate, 👍/👎 under an assistant reply.
 *
 * Always visible on touch screens and for the latest reply; revealed on hover or
 * keyboard focus otherwise (never hover-only — that would hide them from keyboard
 * users).
 */
export function MessageActions({
  chatKey,
  message,
  canRegenerate,
  alwaysVisible,
}: {
  chatKey: string;
  message: ChatMessage;
  canRegenerate: boolean;
  alwaysVisible: boolean;
}) {
  const { chat } = useStores();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
    } catch {
      toast.error("Couldn't copy to the clipboard.");
    }
  };

  const rate = async (rating: FeedbackRating) => {
    try {
      await chat.setFeedback(chatKey, message.id, message.feedback === rating ? null : rating);
    } catch (error) {
      toast.error(describeError(error).title);
    }
  };

  const regenerate = () => {
    if (message.conversationId) void chat.regenerate(message.conversationId);
  };

  return (
    <div
      className={cn(
        "mt-1 flex items-center gap-0.5 transition-opacity",
        alwaysVisible ? "opacity-100" : "opacity-100 md:[@media(hover:hover)_and_(pointer:fine)]:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100",
      )}
    >
      <button type="button" onClick={copy} className={actionClass} aria-label={copied ? "Copied" : "Copy reply"}>
        {copied ? <Check aria-hidden className="h-4 w-4" /> : <Copy aria-hidden className="h-4 w-4" />}
      </button>
      {canRegenerate && (
        <button type="button" onClick={regenerate} className={actionClass} aria-label="Regenerate reply">
          <RefreshCw aria-hidden className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        onClick={() => rate("up")}
        aria-pressed={message.feedback === "up"}
        aria-label="Good reply"
        className={cn(actionClass, message.feedback === "up" && "text-brand")}
      >
        <ThumbsUp aria-hidden className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => rate("down")}
        aria-pressed={message.feedback === "down"}
        aria-label="Bad reply"
        className={cn(actionClass, message.feedback === "down" && "text-destructive")}
      >
        <ThumbsDown aria-hidden className="h-4 w-4" />
      </button>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </div>
  );
}
