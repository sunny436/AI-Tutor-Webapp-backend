import { redirect } from "next/navigation";
import { DashboardShell } from "@/components/dashboard-shell";
import { currentUser } from "@/lib/current-user";

/**
 * The gate for every authenticated page: consult, files, jobs, platform,
 * settings, settings/billing.
 *
 * FAIL-CLOSED, deliberately. It would have been less code to add a "render
 * anyway when signed out" branch here and keep `/` inside this group — but that
 * converts the single gate for six routes into a fail-open one, so a later edit
 * to the middleware matcher would silently serve dashboard pages bare instead of
 * redirecting. `/` lives outside this group instead; see `[locale]/page.tsx`.
 *
 * The chrome moved to `<DashboardShell>` because that root page needs to render
 * exactly the same thing.
 */
export default async function Layout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  if (!user?.username) {
    return redirect("/onboarding");
  }
  return <DashboardShell>{children}</DashboardShell>;
}
