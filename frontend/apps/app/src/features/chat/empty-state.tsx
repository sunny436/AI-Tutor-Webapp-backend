"use client";

import { ChevronRight } from "lucide-react";

import { useUser } from "@/components/user-context";
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

/** What a new, empty chat shows: a greeting, the question, and four ways to start. */
export function ChatEmptyState({ chatKey }: { chatKey: string }) {
  const { chat } = useStores();
  const { user } = useUser();
  const firstName = user.displayName?.trim().split(/\s+/)[0];

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-8 px-4 py-10 sm:px-6">
      <div className="text-center">
        <p className="text-sm font-medium text-text-secondary">Namaste{firstName ? `, ${firstName}` : ""} 👋</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          How can I help your studies today?
        </h2>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-text-secondary">
          Ask a doubt, practise board questions, or get step-by-step maths and science solutions.
        </p>
      </div>

      <ul aria-label="Suggested questions" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {QUICK_PROMPTS.map((item) => (
          <li key={item.title}>
            <button
              type="button"
              onClick={() => void chat.send(chatKey, item.prompt)}
              className="focus-ring group flex w-full items-center justify-between gap-3 rounded-2xl border border-border px-4 py-3 text-left transition-colors hover:bg-surface-2"
            >
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-foreground">{item.title}</span>
                <span className="block text-xs text-text-secondary">{item.subject}</span>
              </span>
              <ChevronRight
                aria-hidden
                className="h-4 w-4 shrink-0 text-text-secondary opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
              />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
