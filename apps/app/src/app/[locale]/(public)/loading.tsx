import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";

/**
 * The public routes' loading state — which is to say, the login page's.
 *
 * WHY IT EXISTS
 *
 * `(dashboard)/loading.tsx` was added for exactly this bug and its comment still
 * describes it best: a navigation held the OLD page on screen for the whole round
 * trip and then swapped, so a slow connection looked like a dead click and people
 * pressed the link again. The dashboard was fixed. The public routes never were.
 *
 * That is the path most visitors actually take. Every call to action on the
 * landing page — "Get started", "Start a consultation", "Sign in" — goes to
 * `/login`, and until this file existed the click produced NOTHING: the landing
 * page just sat there through a redirect and a dynamic render.
 *
 * It also buys back the prefetch. Next cannot usefully prefetch a dynamic route
 * with no loading boundary, so `<Link>` prefetching was doing nothing for the
 * one navigation that matters most on this site.
 *
 * WHY NOT `PageShell`
 *
 * The dashboard's loading state wraps `PageShell`, and this one deliberately does
 * not. `PageShell` is a centred, max-width, padded reading column — right for the
 * fourteen pages inside the dashboard, wrong for a full-bleed split screen. Using
 * it here would promise a layout the login page does not have. The primitives
 * (`Skeleton`, `SkeletonGroup`) are shared; only the shell differs, because the
 * shells genuinely differ.
 *
 * WHY IT IS AT `(public)/` AND NOT `[locale]/`
 *
 * A `[locale]/loading.tsx` would also stream a skeleton over the landing page and
 * over `/library` on first paint — trading one perception problem for another, on
 * the two surfaces a first-time visitor and a search crawler see. This group
 * holds `/login` and nothing else, which is the reported path.
 *
 * The shapes below mirror `(public)/login/page.tsx`: its split at `lg`, its
 * hidden-below-`lg` left panel, and the `w-72` form column that `auth-form.tsx`
 * uses. Close enough that nothing jumps when the real page arrives, vague enough
 * that it is not promising specific copy — per the dashboard file's reasoning,
 * a skeleton that promises the wrong layout is worse than one that promises
 * nothing.
 *
 * Plain `div`s throughout, never a `<form>`: `e2e/auth-live.js` scopes its
 * selectors to `form.w-72` and `form.w-64` to tell the password form from the
 * magic-code one, and a skeleton that matched those would be found first.
 */
export default function Loading() {
  return (
    <div className="relative min-h-dvh w-full bg-background lg:grid lg:grid-cols-[1.05fr_1fr]">
      {/* The marketing panel. Hidden below `lg`, exactly as on the real page —
          on a phone the form is the whole screen, so a skeleton for a panel that
          will never render would be a lie about what is loading. */}
      <section className="relative hidden flex-col justify-between border-r border-border bg-surface p-10 lg:flex xl:p-14">
        <SkeletonGroup label="Loading sign in">
          <div className="flex items-center gap-2.5">
            <Skeleton className="h-9 w-9 rounded-xl" />
            <Skeleton className="h-4 w-28" />
          </div>

          <div className="mt-16 max-w-md">
            <Skeleton className="h-8 w-72 max-w-full" />
            <Skeleton className="mt-3 h-4 w-80 max-w-full" />
            <Skeleton className="mt-1.5 h-4 w-64 max-w-full" />
            <Skeleton className="mt-7 h-32 rounded-xl" />
          </div>

          <ul className="mt-16 space-y-4">
            {[0, 1, 2].map((row) => (
              <li key={row} className="flex gap-3">
                <Skeleton className="h-7 w-7 shrink-0 rounded-lg" />
                <div className="min-w-0 flex-1">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="mt-1.5 h-3 w-56 max-w-full" />
                </div>
              </li>
            ))}
          </ul>
        </SkeletonGroup>
      </section>

      {/* The form column. `w-72` matches `auth-form.tsx`, so the fields land
          where the skeleton said they would. */}
      <div className="relative flex min-h-dvh flex-col items-center justify-center px-4 py-10 lg:min-h-0">
        <SkeletonGroup
          // The panel above already announces "Loading sign in", and it is only
          // rendered at `lg`. On a phone this column is the entire page, so it
          // has to carry the announcement itself.
          label="Loading sign in"
          className="flex w-full flex-col items-center"
        >
          {/* The compact header, shown only below `lg` — the mirror of the
              panel's visibility, so exactly one of the two is ever on screen. */}
          <div className="mb-7 flex flex-col items-center lg:hidden">
            <Skeleton className="h-11 w-11 rounded-xl" />
            <Skeleton className="mt-3 h-5 w-40" />
            <Skeleton className="mt-2 h-3 w-56 max-w-full" />
          </div>

          <div className="mb-6 hidden w-72 lg:block">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="mt-2 h-3 w-60 max-w-full" />
          </div>

          <div className="flex w-72 max-w-full flex-col gap-3">
            <Skeleton className="h-10 rounded-lg" />
            <Skeleton className="h-10 rounded-lg" />
            <Skeleton className="h-10 rounded-lg" />
          </div>

          <Skeleton className="mt-4 h-3 w-48" />
        </SkeletonGroup>
      </div>
    </div>
  );
}
