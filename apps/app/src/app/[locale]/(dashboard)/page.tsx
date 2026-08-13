"use client";

/**
 * Home — what you see after signing in.
 *
 * EVERY NUMBER HERE IS REAL. That was already mostly true and is now true
 * without exception; three things had to go for it to be.
 *
 * 1. "AI Insight" was a hardcoded paragraph — "finish dinner before 8 PM" —
 *    under a Sparkles icon and an AI label. No model produced it and it was the
 *    same sentence for every user forever. Presenting fixed copy as generated
 *    guidance is the exact thing the brief forbids, and on a health product it
 *    is worse than decorative: it is unearned authority. Replaced with the one
 *    honest claim in its place — what the assistant actually does, and a way in.
 *
 * 2. "Diet Plan" and "Yoga Routine" quick actions pointed at `/consult` with no
 *    parameters, so both opened an empty chat. They advertised two features that
 *    do not exist as features; they are sections of a generated plan.
 *
 * 3. Open Jobs and Members were two of the four headline numbers on a personal
 *    health screen. Both are still collected, still queried, and still shown on
 *    /platform — they simply are not what someone opens a wellness assistant to
 *    find out.
 */

import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@v1/ui/card";
import { EmptyState } from "@v1/ui/empty-state";
import { PageShell } from "@v1/ui/page-shell";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { useQuery } from "convex/react";
import {
  ArrowUpRight,
  CalendarDays,
  FileText,
  MessageSquare,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <Card variant="raised" className="p-4">
      <span
        aria-hidden
        className="mb-3 grid h-9 w-9 place-items-center rounded-lg bg-brand-soft text-brand"
      >
        <Icon className="h-[18px] w-[18px]" />
      </span>
      <p className="text-xs font-medium text-text-secondary">{label}</p>
      <p className="mt-0.5 font-display text-2xl font-semibold tabular-nums tracking-tight text-foreground">
        {value ?? "—"}
      </p>
      {hint && <p className="mt-0.5 text-xs text-text-secondary">{hint}</p>}
    </Card>
  );
}

export default function Home() {
  const { current } = useWorkspace();
  const scoped = current ? { workspaceId: current } : "skip";
  const stats = useQuery(api.dashboard.stats, scoped);
  const user = useQuery(api.users.getUser);
  const sessions = useQuery(api.chats.listSessions);
  const loadingSessions = sessions === undefined;
  const list = sessions ?? [];

  const bars = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const out: { label: string; count: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const start = new Date(today);
      start.setDate(today.getDate() - i);
      const end = new Date(start);
      end.setDate(start.getDate() + 1);
      const count = list.filter(
        (s) => s.updatedAt >= start.getTime() && s.updatedAt < end.getTime(),
      ).length;
      out.push({
        label: start.toLocaleDateString(undefined, { weekday: "short" }),
        count,
      });
    }
    return out;
  }, [list]);

  const maxBar = Math.max(1, ...bars.map((b) => b.count));
  const thisWeek = bars.reduce((total, b) => total + b.count, 0);
  const recent = list.slice(0, 5);

  return (
    <PageShell>
      <div className="mb-6 sm:mb-8">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Namaste{user?.name ? `, ${user.name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Describe what&apos;s troubling you and get a plan drawn from Ayurveda — with
          its sources shown.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          icon={MessageSquare}
          label="Consultations"
          value={loadingSessions ? "—" : list.length}
          hint={list.length ? "Saved to your account" : "None yet"}
        />
        <Stat icon={CalendarDays} label="This week" value={loadingSessions ? "—" : thisWeek} />
        <Stat icon={FileText} label="Reports" value={stats?.files} hint="Uploaded by you" />
      </div>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle as="h2" className="text-sm font-semibold">
              Consultations · last 7 days
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loadingSessions ? (
              <SkeletonGroup className="flex h-32 items-end gap-3">
                {bars.map((b) => (
                  <Skeleton key={b.label} className="h-1/2 flex-1" />
                ))}
              </SkeletonGroup>
            ) : bars.every((b) => b.count === 0) ? (
              // With no data every bar renders at 2px and 25% opacity, which
              // reads as a broken chart rather than an empty one.
              <div className="flex h-32 flex-col items-center justify-center gap-1 text-center">
                <p className="text-sm text-text-secondary">No consultations yet</p>
                <p className="text-xs text-text-secondary/70">
                  Your weekly activity will appear here.
                </p>
              </div>
            ) : (
              <div className="flex h-32 items-end gap-3">
                {bars.map((b) => (
                  <div key={b.label} className="flex flex-1 flex-col items-center gap-1.5">
                    <div className="flex h-full w-full items-end justify-center">
                      <div
                        className="w-full rounded-t-md bg-brand transition-all"
                        style={{
                          height: `${(b.count / maxBar) * 100}%`,
                          minHeight: b.count ? "6px" : "2px",
                          opacity: b.count ? 1 : 0.2,
                        }}
                      />
                    </div>
                    {/* The count is the information; the bar is the picture of
                        it. Screen readers get the number, not the geometry. */}
                    <span className="text-2xs text-text-secondary">
                      <span aria-hidden>{b.label}</span>
                      <span className="sr-only">
                        {b.label}: {b.count} consultation{b.count === 1 ? "" : "s"}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="border-brand/20 bg-brand-soft/40">
          <CardHeader className="pb-2">
            <CardTitle as="h2" className="text-base">
              Start a consultation
            </CardTitle>
          </CardHeader>
          <CardContent className="pb-5">
            <p className="text-sm leading-relaxed text-text-secondary">
              One line is enough — in English, Hindi or Hinglish. You&apos;ll get a few
              quick questions to tap through, then a plan with its root cause, food
              chart, yoga and daily routine.
            </p>
            <Button asChild className="mt-4">
              <Link href="/consult">
                Describe a problem
                <ArrowUpRight aria-hidden className="ml-1.5 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle as="h2" className="text-sm font-semibold">
              Recent consultations
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {loadingSessions ? (
              <SkeletonGroup className="space-y-2">
                {["a", "b", "c"].map((k) => (
                  <Skeleton key={k} className="h-12 w-full" />
                ))}
              </SkeletonGroup>
            ) : recent.length === 0 ? (
              <EmptyState
                icon={MessageSquare}
                title="No consultations yet"
                description="Tell the assistant what's troubling you and it will build you a plan."
                action={
                  <Button asChild size="sm">
                    <Link href="/consult">Start one</Link>
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-border">
                {recent.map((s) => (
                  <li key={s.sessionId}>
                    <Link
                      href={`/consult?c=${s.sessionId}`}
                      className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-surface-2"
                    >
                      <span
                        aria-hidden
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"
                      >
                        <MessageSquare className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                        {s.title}
                      </span>
                      <time
                        dateTime={new Date(s.updatedAt).toISOString()}
                        className="shrink-0 text-xs tabular-nums text-text-secondary"
                      >
                        {new Date(s.updatedAt).toLocaleDateString(undefined, {
                          day: "numeric",
                          month: "short",
                        })}
                      </time>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle as="h2" className="text-sm font-semibold">
              Quick actions
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {[
              {
                href: "/consult",
                icon: MessageSquare,
                title: "New consultation",
                sub: "Describe a problem",
              },
              {
                href: "/files",
                icon: Upload,
                title: "Upload a report",
                sub: "PDF or photo — the assistant can read it",
              },
            ].map((q) => (
              <Card key={q.title} variant="interactive" className="p-0">
                <Link href={q.href} className="flex items-start gap-3 rounded-xl p-3.5">
                  <span
                    aria-hidden
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"
                  >
                    <q.icon className="h-[18px] w-[18px]" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-foreground">
                      {q.title}
                    </span>
                    <span className="block text-xs leading-snug text-text-secondary">
                      {q.sub}
                    </span>
                  </span>
                </Link>
              </Card>
            ))}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}
