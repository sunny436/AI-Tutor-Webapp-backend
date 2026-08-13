"use client";

import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { useMutation, usePaginatedQuery } from "convex/react";
import { ListChecks } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const badge: Record<string, string> = {
  pending: "bg-warning-soft text-warning",
  running: "bg-info-soft text-info",
  done: "bg-brand-soft text-brand",
  error: "bg-destructive/10 text-destructive",
};

export default function JobsPage() {
  const { current } = useWorkspace();
  const { results: jobs, status, loadMore } = usePaginatedQuery(
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
      await createJob({ workspaceId: current, kind: "demo", input: { prompt: "hello world" } });
      toast.success("Job queued");
    } catch {
      toast.error("Couldn't queue job");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="min-h-full w-full px-4 py-6 sm:px-6 sm:py-8">
      <div className="mx-auto w-full max-w-screen-xl space-y-5">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
              <ListChecks className="h-6 w-6 text-brand" /> Jobs
            </h1>
            <p className="mt-0.5 text-sm text-text-secondary">Async tasks — created in Convex, processed by the backend, updated live.</p>
          </div>
          <button type="button" onClick={runDemo} disabled={pending || !current}
            className="inline-flex h-10 items-center rounded-xl bg-brand px-4 text-sm font-medium text-brand-foreground elev-1 transition hover:brightness-110 disabled:opacity-50">
            {pending ? "Creating…" : "Run demo job"}
          </button>
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
          <table className="w-full text-sm">
            <thead className="sticky top-0 border-b border-border bg-card text-left">
              <tr className="text-[11px] uppercase tracking-wide text-text-secondary">
                <th className="px-4 py-3 font-semibold">Kind</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Result</th>
                <th className="px-4 py-3 font-semibold">Updated</th>
              </tr>
            </thead>
            <tbody>
              {status === "LoadingFirstPage" && (
                <tr><td className="px-4 py-6 text-text-secondary" colSpan={4}>Loading…</td></tr>
              )}
              {status !== "LoadingFirstPage" && jobs.length === 0 && (
                <tr><td className="px-4 py-8 text-center text-text-secondary" colSpan={4}>No jobs yet.</td></tr>
              )}
              {jobs.map((job) => (
                <tr key={job._id} className="border-b border-border/50 transition last:border-0 hover:bg-primary/[0.03]">
                  <td className="px-4 py-3 font-mono text-foreground">{job.kind}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge[job.status] ?? ""}`}>{job.status}</span>
                  </td>
                  <td className="max-w-[420px] truncate px-4 py-3 font-mono text-xs text-text-secondary">
                    {job.result ? JSON.stringify(job.result) : job.error ? `⚠ ${job.error}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{new Date(job.updatedAt).toLocaleTimeString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {status === "CanLoadMore" && (
          <div className="flex justify-center"><Button variant="outline" size="sm" onClick={() => loadMore(20)}>Load more</Button></div>
        )}
        {status === "LoadingMore" && <p className="text-center text-sm text-text-secondary">Loading…</p>}
      </div>
    </div>
  );
}
