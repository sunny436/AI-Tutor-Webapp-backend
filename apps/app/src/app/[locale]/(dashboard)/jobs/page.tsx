"use client";

import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Badge } from "@v1/ui/badge";
import { Button } from "@v1/ui/button";
import { EmptyState } from "@v1/ui/empty-state";
import { PageHeader, PageShell } from "@v1/ui/page-shell";
import { Skeleton } from "@v1/ui/skeleton";
import { useMutation, usePaginatedQuery } from "convex/react";
import { AlertTriangle, ListChecks, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

// `done` is `success`, not `brand`. See the note in badge.tsx: "this worked"
// and "this is our colour" are different statements, and a product where every
// good outcome is brand-coloured has no way left to say "good".
const STATUS_VARIANT: Record<
  string,
  "neutral" | "brand" | "success" | "warning" | "danger" | "info"
> = {
  pending: "warning",
  running: "info",
  done: "success",
  error: "danger",
};

const COLUMNS = ["Kind", "Status", "Result", "Updated"];

export default function JobsPage() {
  const { current } = useWorkspace();
  const {
    results: jobs,
    status,
    loadMore,
  } = usePaginatedQuery(
    api.jobs.listPaged,
    current ? { workspaceId: current } : "skip",
    { initialNumItems: 20 },
  );
  const createJob = useMutation(api.jobs.create);
  const [pending, setPending] = useState(false);

  const runDemo = async () => {
    if (!current) return;
    setPending(true);
    try {
      await createJob({
        workspaceId: current,
        kind: "demo",
        input: { prompt: "hello world" },
      });
      toast.success("Job queued");
    } catch {
      toast.error("Couldn't queue job");
    } finally {
      setPending(false);
    }
  };

  const loading = status === "LoadingFirstPage";
  const empty = !loading && jobs.length === 0;

  const action = (
    <Button onClick={runDemo} disabled={pending || !current}>
      {pending ? "Creating…" : "Run demo job"}
    </Button>
  );

  return (
    // This was the only dashboard page with its own container and no wash, and
    // the only one measuring `max-w-screen-xl` while PageShell pages measured
    // `max-w-6xl`. `width="wide"` keeps the room a table wants without keeping
    // a third measure in the app.
    <PageShell width="wide">
      <PageHeader
        title="Jobs"
        description="Async tasks — created in Convex, processed by the backend, updated live."
        icon={ListChecks}
        action={action}
      />

      {empty ? (
        // A table head with no body reads as a broken table rather than as an
        // empty list, so the whole table is replaced while there is nothing in
        // it.
        <EmptyState
          icon={ListChecks}
          title="No jobs yet"
          description="Queued work shows up here as it runs, and updates live."
          action={action}
        />
      ) : (
        // `overflow-x-auto`, not `overflow-hidden`: four columns plus a
        // timestamp do not fit 375px, and the old value CLIPPED the Updated
        // column instead of letting it scroll — it was unreachable at any zoom.
        // `min-w` gives it something to scroll rather than crushing every cell.
        <div className="w-full overflow-x-auto rounded-xl border border-border bg-card">
          <table
            className="w-full min-w-[38rem] caption-bottom text-sm"
            aria-busy={loading || undefined}
          >
            {/* A <caption>, not a <SkeletonGroup>: that primitive renders a
                <div>, which is not valid inside a table. Same job — announce
                the wait once — with markup the table will accept. */}
            {loading && <caption className="sr-only">Loading jobs</caption>}
            <thead className="bg-surface-2/60">
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c}
                    scope="col"
                    className="h-10 whitespace-nowrap px-4 text-left align-middle text-xs font-semibold uppercase tracking-wide text-text-secondary"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="[&_tr:last-child]:border-0">
              {loading &&
                [0, 1, 2, 3, 4].map((row) => (
                  <tr key={row} className="border-b border-border">
                    {COLUMNS.map((c) => (
                      <td key={c} className="px-4 py-3">
                        <Skeleton className="h-4 w-24" />
                      </td>
                    ))}
                  </tr>
                ))}
              {jobs.map((job) => (
                <tr
                  key={job._id}
                  className="border-b border-border transition-colors hover:bg-surface-2/50"
                >
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-foreground">
                    {job.kind}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={STATUS_VARIANT[job.status] ?? "neutral"}>
                      {job.status}
                    </Badge>
                  </td>
                  <td className="max-w-[26rem] truncate px-4 py-3 font-mono text-xs text-text-secondary">
                    {job.result ? (
                      JSON.stringify(job.result)
                    ) : job.error ? (
                      // Was a bare "⚠" emoji, which is the only failure signal
                      // in the row and renders differently on every platform.
                      <span className="inline-flex items-center gap-1.5 text-destructive">
                        <AlertTriangle aria-hidden className="h-3.5 w-3.5 shrink-0" />
                        {job.error}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums text-text-secondary">
                    {new Date(job.updatedAt).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(status === "CanLoadMore" || status === "LoadingMore") && (
        <div className="mt-5 flex justify-center">
          {/* A disabled button rather than swapping in a "Loading…" paragraph:
              the control kept its place instead of vanishing and reflowing the
              page under the pointer that just clicked it. */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadMore(20)}
            disabled={status === "LoadingMore"}
          >
            {status === "LoadingMore" ? (
              <>
                <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" />
                Loading…
              </>
            ) : (
              "Load more"
            )}
          </Button>
        </div>
      )}
    </PageShell>
  );
}
