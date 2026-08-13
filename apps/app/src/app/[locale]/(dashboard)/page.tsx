"use client";

/**
 * Dashboard (home) — premium redesign. Uses REAL data:
 *  - api.dashboard.stats (jobs/files/members/usage)
 *  - api.chats.listSessions (consultations + 7-day activity)
 *  - api.audit.recent (recent activity)
 * Sidebar and business logic are untouched.
 */

import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { useQuery } from "convex/react";
import {
  Activity, Apple, ArrowUpRight, FileText, ListChecks, MessageSquare,
  Sparkles, Upload, Users, Wind,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

function KPI({
  icon: Icon,
  tint,
  label,
  value,
  sub,
}: {
  icon: LucideIcon;
  tint: string;
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="group rounded-2xl border border-border bg-card p-4 shadow-sm transition hover:-translate-y-1 hover:border-emerald-500/30 hover:shadow-lg">
      <div className={`mb-3 grid h-10 w-10 place-items-center rounded-xl ${tint}`}>
        <Icon className="h-5 w-5" />
      </div>
      <p className="text-xs font-medium text-primary/50">{label}</p>
      <p className="mt-1 text-2xl font-bold tracking-tight text-primary">{value ?? "—"}</p>
      {sub && <p className="mt-1 text-[11px] text-emerald-600 dark:text-emerald-400">{sub}</p>}
    </div>
  );
}

export default function Home() {
  const { current } = useWorkspace();
  const scoped = current ? { workspaceId: current } : "skip";
  const stats = useQuery(api.dashboard.stats, scoped);
  const audit = useQuery(api.audit.recent, scoped);
  const user = useQuery(api.users.getUser);
  const sessions = useQuery(api.chats.listSessions) ?? [];

  const bars = useMemo(() => {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const out: { label: string; count: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const start = new Date(today); start.setDate(today.getDate() - i);
      const end = new Date(start); end.setDate(start.getDate() + 1);
      const count = sessions.filter((s) => s.updatedAt >= start.getTime() && s.updatedAt < end.getTime()).length;
      out.push({ label: start.toLocaleDateString(undefined, { weekday: "short" }), count });
    }
    return out;
  }, [sessions]);
  const maxBar = Math.max(1, ...bars.map((b) => b.count));

  const QUICK = [
    { href: "/consult", icon: MessageSquare, tint: "tint-em", t: "New Consult", s: "Ask about a problem" },
    { href: "/files", icon: Upload, tint: "tint-bl", t: "Upload Report", s: "PDF or image" },
    // No `?cat=` any more — one chat handles every kind of consultation, and the
    // AI works out what's needed from what the user describes.
    { href: "/consult", icon: Apple, tint: "tint-lime", t: "Diet Plan", s: "Get a food chart" },
    { href: "/consult", icon: Wind, tint: "tint-tl", t: "Yoga Routine", s: "Daily practice" },
  ];

  return (
    <div className="min-h-[calc(100vh-3rem)] w-full bg-gradient-to-br from-emerald-50 via-white to-teal-50 px-6 py-7 dark:from-zinc-950 dark:via-black dark:to-emerald-950/30">
      <style>{`
        .tint-em{background:rgba(16,185,129,.14);color:#059669}.dark .tint-em{color:#34d399}
        .tint-bl{background:rgba(59,130,246,.14);color:#2563eb}.dark .tint-bl{color:#60a5fa}
        .tint-am{background:rgba(245,158,11,.14);color:#d97706}.dark .tint-am{color:#fbbf24}
        .tint-tl{background:rgba(20,184,166,.14);color:#0d9488}.dark .tint-tl{color:#2dd4bf}
        .tint-lime{background:rgba(132,204,22,.14);color:#65a30d}.dark .tint-lime{color:#a3e635}
      `}</style>
      <div className="mx-auto w-full max-w-screen-xl space-y-5">
        {/* Greeting */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-primary">
            Namaste{user?.name ? `, ${user.name}` : ""} 🙏
          </h1>
          <p className="mt-0.5 text-sm text-primary/60">Here&apos;s your wellness overview.</p>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KPI icon={MessageSquare} tint="tint-em" label="Consultations" value={sessions.length} sub={sessions.length ? "Saved to your account" : undefined} />
          <KPI icon={ListChecks} tint="tint-bl" label="Open Jobs" value={stats?.openJobs} sub={`${stats?.jobs ?? 0} total`} />
          <KPI icon={FileText} tint="tint-am" label="Files" value={stats?.files} />
          <KPI icon={Users} tint="tint-tl" label="Members" value={stats?.members} />
        </div>

        {/* Chart + AI insight */}
        <div className="grid items-start gap-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-primary">Consultations · last 7 days</h2>
              <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] text-primary/50">This week</span>
            </div>
            {/* With no consultations yet every bar renders at 2px and 25%
                opacity, which reads as a broken chart rather than an empty one.
                Say so instead. */}
            {/* Not `maxBar === 0`: maxBar is Math.max(1, …) so it never reaches
                zero. Ask the bars themselves. */}
            {bars.every((b) => b.count === 0) ? (
              <div className="flex h-32 flex-col items-center justify-center gap-1 text-center">
                <p className="text-sm text-primary/50">No consultations yet</p>
                <p className="text-xs text-primary/35">
                  Your weekly activity will appear here.
                </p>
              </div>
            ) : (
            <div className="flex h-32 items-end gap-3">
              {/* Keyed by the day label, which is unique across a 7-day window
                  and stable as the data updates — unlike the array index. */}
              {bars.map((b) => (
                <div key={b.label} className="flex flex-1 flex-col items-center gap-1.5">
                  <div className="flex w-full items-end justify-center" style={{ height: "100%" }}>
                    <div className="w-full rounded-t-lg bg-gradient-to-t from-emerald-500 to-teal-400 transition-all"
                      style={{ height: `${(b.count / maxBar) * 100}%`, minHeight: b.count ? "6px" : "2px", opacity: b.count ? 1 : 0.25 }} />
                  </div>
                  <span className="text-[10px] text-primary/40">{b.label}</span>
                </div>
              ))}
            </div>
            )}
          </div>

          <div className="rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/10 to-teal-500/5 p-5 shadow-sm">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-primary">
              <Sparkles className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> AI Insight
            </div>
            <p className="text-sm leading-relaxed text-primary/75">
              Small, consistent habits work best in Ayurveda. Try finishing dinner before <b>8 PM</b> and a short walk after meals to support digestion.
            </p>
            <Link href="/consult" className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 px-3.5 py-2 text-xs font-semibold text-white shadow-md shadow-emerald-500/25 transition hover:brightness-105">
              Start a consult <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>

        {/* Activity + Quick actions */}
        <div className="grid items-start gap-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="rounded-2xl border border-border bg-card shadow-sm">
            <div className="flex items-center gap-2 border-b border-border px-5 py-3.5">
              <Activity className="h-4 w-4 text-primary/50" />
              <h2 className="text-sm font-semibold text-primary">Recent Activity</h2>
            </div>
            <div>
              {audit === undefined ? (
                <div className="px-5 py-6 text-sm text-primary/40">Loading…</div>
              ) : audit.length ? (
                audit.map((a) => (
                  <div key={a._id} className="flex items-center gap-3 border-b border-border/50 px-5 py-3 last:border-0">
                    <span className="grid h-8 w-8 place-items-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                      <Activity className="h-4 w-4" />
                    </span>
                    <span className="font-mono text-sm text-primary/80">{a.action}</span>
                    <span className="ml-auto text-xs text-primary/45">{new Date(a.at).toLocaleString()}</span>
                  </div>
                ))
              ) : (
                <div className="px-5 py-8 text-center text-sm text-primary/40">No activity yet — start your first consult 🌿</div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-primary">Quick Actions</h2>
            <div className="grid grid-cols-2 gap-3">
              {QUICK.map((q) => (
                <Link key={q.t} href={q.href}
                  className="rounded-xl border border-border bg-background p-3.5 transition hover:-translate-y-0.5 hover:border-emerald-500/40 hover:shadow-md">
                  <span className={`mb-2 grid h-9 w-9 place-items-center rounded-lg ${q.tint}`}><q.icon className="h-4.5 w-4.5" /></span>
                  <p className="text-sm font-semibold text-primary">{q.t}</p>
                  <p className="text-[11px] text-primary/50">{q.s}</p>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
