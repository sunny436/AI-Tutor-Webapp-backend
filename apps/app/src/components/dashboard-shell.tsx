import { WorkspaceProvider } from "@/lib/workspace-provider";
import { Toaster } from "sonner";
import { CommandPalette } from "@/app/[locale]/(dashboard)/_components/command-palette";
import { Sidebar } from "@/app/[locale]/(dashboard)/_components/sidebar";
import { Topbar } from "@/app/[locale]/(dashboard)/_components/topbar";

/**
 * The signed-in chrome: sidebar, topbar, toasts, command palette.
 *
 * Lifted out of `(dashboard)/layout.tsx` because `/` no longer lives in that
 * route group. It had to move OUT of the group so that a signed-out visitor
 * could be shown the landing page — the group's layout fetches the user and
 * redirects to `/onboarding` before any page inside it renders, so a "public"
 * page in there would still bounce to login. See `[locale]/page.tsx`.
 *
 * Both the group layout and the root page now render this, so the two paths
 * cannot drift into showing different chrome.
 */
export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <div className="min-h-dvh w-full bg-background md:flex">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <div className="min-h-0 flex-1">{children}</div>
        </main>
      </div>
      <Toaster richColors position="top-right" />
      <CommandPalette />
    </WorkspaceProvider>
  );
}
