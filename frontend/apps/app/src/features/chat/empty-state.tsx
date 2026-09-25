"use client";

import { ChevronRight, Sparkles } from "lucide-react";

import { BrandMark } from "@/components/brand/brand-mark";
import { useUser } from "@/components/user-context";
import { APP_NAME } from "@/lib/brand";
import { useStores } from "./chat-context";

/**
 * Suggested first questions. Each one is sent exactly as if it had been typed
 * into the composer (`chat.send`), so it is an ordinary message: nothing here
 * needs, or pretends to have, anything the chat does not already do.
 */
const QUICK_PROMPTS = [
  {
    title: "Explain Photosynthesis",
    subject: "Class 10 Biology Ch 6",
    prompt: "Explain Photosynthesis for Class 10 CBSE with chemical equation.",
  },
  {
    title: "Quadratic Formula",
    subject: "Class 10 Maths Ch 4",
    prompt: "Give me the Quadratic Formula and how to find roots step by step.",
  },
  {
    title: "Newton’s 3rd Law",
    subject: "Physics Class 9/10",
    prompt: "Explain Newton’s Third Law of Motion with real-life daily examples.",
  },
  {
    title: "French Revolution Recapped",
    subject: "Class 9/10 History",
    prompt: "Summarize key causes of French Revolution in 5 bullet points.",
  },
] as const;

/** What a new, empty chat shows: a welcome, four ways to start, and a greeting. */
export function ChatEmptyState({ chatKey }: { chatKey: string }) {
  const { chat } = useStores();
  const { user } = useUser();
  const firstName = user.displayName?.trim().split(/\s+/)[0];

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-between gap-8 px-3 py-6 sm:px-6 sm:py-8">
      <div>
        <div className="mb-8 text-center">
          <span
            aria-hidden
            className="bg-hero mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl text-hero-foreground shadow-lg shadow-brand/25"
          >
            <Sparkles className="h-8 w-8" />
          </span>
          <h2 className="font-display text-2xl font-black text-foreground">How can I help your studies today?</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
            Ask doubts, practice board questions, or get instant step-by-step math and science solutions.
          </p>
        </div>

        <ul aria-label="Suggested questions" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {QUICK_PROMPTS.map((item) => (
            <li key={item.title}>
              <button
                type="button"
                onClick={() => void chat.send(chatKey, item.prompt)}
                className="focus-ring group w-full rounded-2xl border border-border bg-card p-4 text-left elev-1 transition-all hover:border-brand/50 hover:elev-2"
              >
                <span className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-bold text-foreground transition-colors group-hover:text-brand">
                    {item.title}
                  </span>
                  <ChevronRight
                    aria-hidden
                    className="h-4 w-4 shrink-0 text-text-secondary transition-colors group-hover:text-brand"
                  />
                </span>
                <span className="text-xs text-text-secondary">{item.subject}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* A greeting, not a message: it is not in the conversation, so it is not an article. */}
      <div className="flex gap-3">
        <BrandMark size={36} className="mt-1 rounded-xl" />
        <p className="max-w-[85%] rounded-2xl rounded-tl-none border border-border bg-card p-4 text-sm leading-relaxed text-foreground elev-1 sm:max-w-[75%]">
          Namaste{firstName ? ` ${firstName}` : ""}! 👋 I'm {APP_NAME}, your personal AI tutor. Ask me any doubt from
          your syllabus. What topic should we master today?
        </p>
      </div>
    </div>
  );
}
