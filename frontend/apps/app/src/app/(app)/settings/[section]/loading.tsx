import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";

/** While a section's page is on its way (a slow network), inside the workspace that stays put. */
export default function SectionLoading() {
  return (
    <SkeletonGroup label="Loading settings" className="space-y-4">
      <Skeleton className="h-8 w-56 max-w-full rounded-lg" />
      <Skeleton className="h-4 w-96 max-w-full rounded" />
      <Skeleton className="mt-6 h-64 w-full rounded-2xl" />
    </SkeletonGroup>
  );
}
