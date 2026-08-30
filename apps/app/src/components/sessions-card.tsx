"use client";

import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { useMutation, useQuery } from "convex/react";
import { toast } from "sonner";

export function SessionsCard() {
  const sessions = useQuery(api.sessions.mySessions);
  const revokeSession = useMutation(api.sessions.revokeSession);
  const revokeOthers = useMutation(api.sessions.revokeOtherSessions);

  return (
    <div className="flex w-full flex-col rounded-xl border border-border bg-card elev-1">
      <div className="flex w-full flex-wrap items-start justify-between gap-3 p-5">
        <div className="flex flex-col gap-1">
          <h3 className="font-display text-base font-semibold tracking-tight text-foreground">
            Active sessions
          </h3>
          <p className="text-sm leading-relaxed text-text-secondary">
            Devices currently signed in to your account.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            const n = await revokeOthers({});
            toast.success(
              n === 0 ? "No other sessions" : `Signed out ${n} other session${n > 1 ? "s" : ""}`,
            );
          }}
        >
          Sign out other sessions
        </Button>
      </div>
      <div className="w-full divide-y divide-border/50 border-t border-border">
        {sessions === undefined ? (
          <p className="px-5 py-4 text-sm text-text-secondary">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="px-5 py-4 text-sm text-text-secondary">No sessions</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s._id}
              // flex-col below sm: a long locale timestamp plus the badge plus
              // the revoke control is about 340px, inside a row with ~295px at
              // 375px, so the three collided on a phone.
              className="flex flex-col items-start justify-between gap-1.5 px-5 py-3 text-sm sm:flex-row sm:items-center sm:gap-3"
            >
              <span className="text-text-secondary">
                Started {new Date(s.createdAt).toLocaleString()}
                {s.isCurrent && (
                  <span className="ml-2 inline-flex items-center rounded-md border border-success/20 bg-success-soft px-2 py-0.5 text-xs font-medium text-success">
                    this device
                  </span>
                )}
              </span>
              {!s.isCurrent && (
                <button
                  type="button"
                  className="focus-ring shrink-0 rounded-md text-xs font-medium text-destructive underline-offset-2 hover:underline"
                  onClick={async () => {
                    await revokeSession({ sessionId: s._id });
                    toast.success("Session revoked");
                  }}
                >
                  revoke
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
