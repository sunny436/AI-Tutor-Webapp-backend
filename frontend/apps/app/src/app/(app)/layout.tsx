import "katex/dist/katex.min.css";
import "@/features/markdown/markdown.css";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppearanceProvider } from "@/components/appearance-provider";
import { PreviewProvider } from "@/components/preview-context";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { UserProvider } from "@/components/user-context";
import { ChatProvider } from "@/features/chat/chat-context";
import { NavigationGuardRoot } from "@/features/navigation/navigation-guard-root";
import { ActivityHeartbeat } from "@/features/progress/activity-heartbeat";
import { SessionKeeper } from "@/features/progress/session-keeper";
import { StudyHeartbeat } from "@/features/study/study-heartbeat";
import { greetingPool } from "@/lib/greeting";
import { previewEnabled } from "@/lib/preview";
import { safeRedirect } from "@/lib/safe-redirect";
import { getAppearance, getCurrentUser, getInitialConversations, getStudyGreetings } from "@/lib/server/session";

/**
 * Every signed-in page. The session is checked HERE, on the server, against the
 * API (`GET /v1/me`) — middleware only saw that a cookie exists.
 *
 *   401          → /api/session/expired (re-checks, clears the cookie, → sign in)
 *   unreachable  → an outage screen, NOT a sign-out
 *   ok           → the app, with the user, their appearance, the first page of chats
 *                  and this week's study greetings already loaded, so the first paint is
 *                  complete (the greeting falls back quietly: lib/greeting.ts)
 *
 * Also decides, per request, whether preview UI may render (lib/preview.ts).
 *
 * The providers, the activity heartbeat and the unsaved-changes guard live HERE, once, so they
 * outlive the switch between the two views under this layout: the app (`(main)/`, inside the
 * app shell) and the Settings workspace (`settings/`, its own frame). A reply keeps streaming
 * and the session is still watched while Settings is open.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  const [session, conversations, appearance, greetings] = await Promise.all([
    getCurrentUser(),
    getInitialConversations(),
    getAppearance(),
    getStudyGreetings(),
  ]);

  if (session.status === "unauthorized") {
    const here = safeRedirect((await headers()).get("x-pathname"));
    redirect(`/api/session/expired${here !== "/" ? `?redirect=${encodeURIComponent(here)}` : ""}`);
  }
  if (session.status !== "ok") return <ServiceUnavailable />;

  return (
    <PreviewProvider enabled={previewEnabled()}>
      <UserProvider user={session.data}>
        <AppearanceProvider initial={appearance.status === "ok" ? appearance.data : null}>
          <ChatProvider
            initialConversations={conversations.status === "ok" ? conversations.data : null}
            greetings={greetingPool(greetings)}
          >
            <ActivityHeartbeat />
            <StudyHeartbeat />
            <SessionKeeper />
            <NavigationGuardRoot />
            {children}
          </ChatProvider>
        </AppearanceProvider>
      </UserProvider>
    </PreviewProvider>
  );
}
