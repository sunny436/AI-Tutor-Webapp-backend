import "katex/dist/katex.min.css";
import "@/features/markdown/markdown.css";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { AppearanceProvider } from "@/components/appearance-provider";
import { PreviewProvider } from "@/components/preview-context";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { UserProvider } from "@/components/user-context";
import { ChatProvider } from "@/features/chat/chat-context";
import { previewEnabled } from "@/lib/preview";
import { safeRedirect } from "@/lib/safe-redirect";
import { getAppearance, getCurrentUser, getInitialConversations } from "@/lib/server/session";

/**
 * Every signed-in page. The session is checked HERE, on the server, against the
 * API (`GET /v1/me`) — middleware only saw that a cookie exists.
 *
 *   401          → /api/session/expired (re-checks, clears the cookie, → sign in)
 *   unreachable  → an outage screen, NOT a sign-out
 *   ok           → the app, with the user, their appearance and the first page of
 *                  chats already loaded, so the sidebar is filled on first paint
 *
 * Also decides, per request, whether preview UI may render (lib/preview.ts).
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  const [session, conversations, appearance] = await Promise.all([
    getCurrentUser(),
    getInitialConversations(),
    getAppearance(),
  ]);

  if (session.status === "unauthorized") {
    const here = safeRedirect(headers().get("x-pathname"));
    redirect(`/api/session/expired${here !== "/" ? `?redirect=${encodeURIComponent(here)}` : ""}`);
  }
  if (session.status !== "ok") return <ServiceUnavailable />;

  return (
    <PreviewProvider enabled={previewEnabled()}>
      <UserProvider user={session.data}>
        <AppearanceProvider initial={appearance.status === "ok" ? appearance.data : null}>
          <ChatProvider initialConversations={conversations.status === "ok" ? conversations.data : null}>
            <AppShell>{children}</AppShell>
          </ChatProvider>
        </AppearanceProvider>
      </UserProvider>
    </PreviewProvider>
  );
}
