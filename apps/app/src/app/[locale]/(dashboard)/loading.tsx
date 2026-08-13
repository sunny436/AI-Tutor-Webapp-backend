import { PageShell } from "@v1/ui/page-shell";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";

/**
 * The dashboard's route-level loading state.
 *
 * There was no `loading.tsx` anywhere in this app. Because `(dashboard)/layout.tsx`
 * awaits `fetchQuery(api.users.getUser)` on the server before rendering anything,
 * a navigation held the OLD page on screen for the whole round trip and then
 * swapped — so a slow connection looked like a dead click, and people pressed the
 * link again.
 *
 * One file at the group level covers every page under it, and Next streams it
 * immediately while the layout's query resolves. The shape below is deliberately
 * generic — a header and a content block — because it stands in for six different
 * pages and a skeleton that promises the wrong layout is worse than one that
 * promises nothing.
 */
export default function Loading() {
  return (
    <PageShell>
      <SkeletonGroup label="Loading page">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="mt-2 h-4 w-80 max-w-full" />
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <Skeleton className="mt-4 h-56" />
      </SkeletonGroup>
    </PageShell>
  );
}
