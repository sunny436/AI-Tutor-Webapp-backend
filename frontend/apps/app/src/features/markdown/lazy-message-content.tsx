"use client";

import { Suspense, lazy, useEffect, useState } from "react";

import type { Citation } from "@/lib/api/types";
import type { TestState } from "./context";

/**
 * The reply renderer, loaded on its own.
 *
 * react-markdown, the remark/rehype plugins, KaTeX and highlight.js are about
 * 170 kB of gzipped JavaScript — about as much as the rest of the chat. In the
 * page's bundle they delayed every chat screen, including a new chat that has
 * nothing to render yet. As a separate chunk they load after the page is
 * interactive: `preloadMessageContent()` starts the download when the chat
 * mounts, so by the time a conversation's messages arrive it is usually there.
 *
 * Until it is, a reply shows as plain text — which is exactly what it is. An opened chat waits for
 * it a little (`useRendererReady`): its replies drawn as plain text and then redrawn moved the whole
 * transcript (a layout shift of 0.23 opening a long chat, 2026-10-23).
 */
type Renderers = typeof import("./message-content");
let loaded: Renderers | null = null;
const waiting = new Set<() => void>();
const load = () =>
  import("./message-content").then((module) => {
    loaded = module;
    for (const notify of waiting) notify();
    waiting.clear();
    return module;
  });

/**
 * What `lazy` loads. Once the renderer is here it is handed over at once, by a thenable that calls
 * back synchronously: `lazy` hears from a resolved Promise only a microtask later, so the first reply
 * drawn would still show its plain-text fallback for a frame and be redrawn (the same layout shift).
 */
function renderer<T>(pick: (module: Renderers) => T): () => Promise<{ default: T }> {
  return () => {
    const ready = loaded;
    if (!ready) return load().then((module) => ({ default: pick(module) }));
    const result = { default: pick(ready) };
    // biome-ignore lint/suspicious/noThenProperty: a synchronous thenable on purpose (React's lazy reads it at once)
    return { then: (resolve: (value: typeof result) => void) => resolve(result) } as unknown as Promise<typeof result>;
  };
}

/** At most this long a transcript waits for the renderer; then its replies show as plain text. */
const RENDERER_WAIT_MS = 2500;

/** Whether replies can be drawn now: the renderer has loaded, failed, or RENDERER_WAIT_MS have passed. */
export function useRendererReady(): boolean {
  const [ready, setReady] = useState(loaded !== null);
  useEffect(() => {
    if (ready) return;
    const finish = () => setReady(true);
    if (loaded) return finish();
    waiting.add(finish);
    load().catch(finish);
    const timer = setTimeout(finish, RENDERER_WAIT_MS);
    return () => {
      waiting.delete(finish);
      clearTimeout(timer);
    };
  }, [ready]);
  return ready;
}

const Renderer = lazy(renderer((module) => module.MessageContent));
const InlineRenderer = lazy(renderer((module) => module.InlineMarkdown));

export function preloadMessageContent(): void {
  void load();
}

/** A short piece of Markdown outside the chat (a missed question, an option): plain text until the renderer loads. */
export function LazyInlineMarkdown({ text }: { text: string }) {
  return (
    <Suspense fallback={text}>
      <InlineRenderer text={text} />
    </Suspense>
  );
}

/**
 * A reply with a study card, a drawn block (diagram, chart, practice) or a file embed. Those
 * have no width of their own, so such a reply takes the whole column instead of fitting its text.
 */
const WIDE =
  /^ {0,3}(?:`{3,}\s*(?:mermaid|chart|mcq|quiz|flashcards|fill-blank|graph|diagram)\b|:{3,}\s*[\w-]|::(?:file|pdf)\{|>\s*\[![A-Za-z]+\])/m;

export function needsFullWidth(content: string): boolean {
  return WIDE.test(content);
}

export function MessageContent({
  content,
  streaming = false,
  citations,
  tests = null,
}: {
  content: string;
  streaming?: boolean;
  citations?: Citation[];
  tests?: TestState | null;
}) {
  return (
    <Suspense
      fallback={
        <div className="min-w-0 whitespace-pre-wrap break-words text-[0.9375rem] leading-7 text-foreground">
          {content}
        </div>
      }
    >
      <Renderer content={content} streaming={streaming} citations={citations} tests={tests} />
    </Suspense>
  );
}
