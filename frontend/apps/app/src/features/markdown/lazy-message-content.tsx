"use client";

import { Suspense, lazy } from "react";

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

export function MessageContent({ content, streaming = false }: { content: string; streaming?: boolean }) {
  return (
    <Suspense
      fallback={
        <div className="min-w-0 whitespace-pre-wrap break-words text-[0.9375rem] leading-7 text-foreground">
          {content}
        </div>
      }
    >
      <Renderer content={content} streaming={streaming} />
    </Suspense>
  );
}
