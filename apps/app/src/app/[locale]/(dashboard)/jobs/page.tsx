"use client";

import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { useMutation, usePaginatedQuery } from "convex/react";
import { ListChecks } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const badge: Record<string, string> = {
  pending: "bg-amber-500/12 text-amber-600 dark:text-amber-400",
  running: "bg-sky-500/12 text-sky-600 dark:text-sky-400",
  done: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400",
  error: "bg-rose-500/12 text-rose-600 dark:text-rose-400",
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
    <div className="min-h-[calc(100vh-3rem)] w-full bg-gradient-to-br from-emerald-50 via-white to-teal-50 px-6 py-7 dark:from-zinc-950 dark:via-black dark:to-emerald-950/30">
      <div className="mx-auto w-full max-w-screen-xl space-y-5">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-primary">
              <ListChecks className="h-6 w-6 text-emerald-600 dark:text-emerald-400" /> Jobs
            </h1>
            <p className="mt-0.5 text-sm text-primary/60">Async tasks — created in Convex, processed by the backend, updated live.</p>
          </div>
          <button type="button" onClick={runDemo} disabled={pending || !current}
            className="inline-flex h-10 items-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/25 transition hover:brightness-105 disabled:opacity-50">
            {pending ? "Creating…" : "Run demo job"}
          </button>
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
          <table className="w-full text-sm">
            <thead className="sticky top-0 border-b border-border bg-card text-left">
              <tr className="text-[11px] uppercase tracking-wide text-primary/50">
                <th className="px-4 py-3 font-semibold">Kind</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Result</th>
                <th className="px-4 py-3 font-semibold">Updated</th>
              </tr>
            </thead>
            <tbody>
              {status === "LoadingFirstPage" && (
                <tr><td className="px-4 py-6 text-primary/40" colSpan={4}>Loading…</td></tr>
              )}
              {status !== "LoadingFirstPage" && jobs.length === 0 && (
                <tr><td className="px-4 py-8 text-center text-primary/40" colSpan={4}>No jobs yet.</td></tr>
              )}
              {jobs.map((job) => (
                <tr key={job._id} className="border-b border-border/50 transition last:border-0 hover:bg-primary/[0.03]">
                  <td className="px-4 py-3 font-mono text-primary/80">{job.kind}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge[job.status] ?? ""}`}>{job.status}</span>
                  </td>
                  <td className="max-w-[420px] truncate px-4 py-3 font-mono text-xs text-primary/55">
                    {job.result ? JSON.stringify(job.result) : job.error ? `⚠ ${job.error}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-primary/50">{new Date(job.updatedAt).toLocaleTimeString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {status === "CanLoadMore" && (
          <div className="flex justify-center"><Button variant="outline" size="sm" onClick={() => loadMore(20)}>Load more</Button></div>
        )}
        {status === "LoadingMore" && <p className="text-center text-sm text-primary/40">Loading…</p>}
      </div>
    </div>
  );
}
