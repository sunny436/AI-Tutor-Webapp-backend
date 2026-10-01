"use client";

import { Suspense, lazy } from "react";

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
 * Until it is, a reply shows as plain text — which is exactly what it is.
 */
const load = () => import("./message-content");

const Renderer = lazy(() => load().then((module) => ({ default: module.MessageContent })));

export function preloadMessageContent(): void {
  void load();
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
