import { redirect } from "next/navigation";
import { DashboardHome } from "@/components/dashboard-home";
import { DashboardShell } from "@/components/dashboard-shell";
import { Landing } from "@/components/landing/landing";
import { currentUser } from "@/lib/current-user";

/**
 * `/` — the landing page to a visitor, the dashboard to a signed-in user.
 *
 * WHY THIS FILE IS HERE AND NOT IN A ROUTE GROUP
 *
 * The obvious approach — keep `/` inside `(dashboard)` and branch on auth in the
 * page — does not work, and fails in a way that looks like it works. Layouts
 * render BEFORE pages, and `(dashboard)/layout.tsx` does:
 *
 *     const user = await currentUser();
 *     if (!user?.username) redirect("/onboarding");
 *
 * `getUser` returns undefined when signed out, so a signed-out visitor to a
 * "public" `/` is redirected to `/onboarding`, which is itself auth-gated, which
 * redirects to `/login`. Five requests, ending on the login page — the exact
 * outcome the landing page exists to avoid, and WORSE than before, because they
 * arrive carrying `?redirect=%2Fonboarding`.
 *
 * A `(marketing)` group alongside `(dashboard)` does not work either: route
 * groups are erased from the URL, so both would resolve to `/[locale]` and Next
 * fails the build with "two parallel pages resolve to the same path".
 *
 * So this page sits outside every group. Exactly one file resolves to
 * `/[locale]`, and it is wrapped only by the root layout. The URL does not move,
 * which means `sidebar.tsx`, `command-palette.tsx`, `onboarding/page.tsx`,
 * `auth-form.tsx`'s `safeRedirect` default and `middleware.ts:151` all keep
 * working untouched.
 *
 * DELIBERATELY NOT A REDIRECT, in either direction. This is the one URL in the
 * app that middleware never bounces, and it must terminate for every auth state.
 * Redirecting from here is how the documented `ERR_TOO_MANY_REDIRECTS` loop gets
 * rebuilt.
 *
 * The onboarding gate below is duplicated from `(dashboard)/layout.tsx` on
 * purpose — this page is not inside that group, so it does not inherit it. Both
 * call `currentUser()` and run the same two-line check, so they stay in step.
 */
export default async function Root() {
  const user = await currentUser();

  if (!user) return <Landing />;
  if (!user.username) redirect("/onboarding");

  return (
    <DashboardShell>
      <DashboardHome />
    </DashboardShell>
  );
}
