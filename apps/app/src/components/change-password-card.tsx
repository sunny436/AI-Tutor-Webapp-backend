"use client";

import { friendlyAuthError, passwordProblems } from "@/lib/auth-errors";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { Input } from "@v1/ui/input";
import { useAction, useQuery } from "convex/react";
import { useState } from "react";
import { toast } from "sonner";

/**
 * Change (or set) the account password.
 *
 * Convex Auth's `Password` provider ships no change-password flow, so this drives
 * `account.setPassword`. Users who signed up with a magic code have no password
 * account at all — for them this is where one gets created, which is also what
 * makes "forgot password" work for them afterwards.
 */
export function ChangePasswordCard() {
  const security = useQuery(api.account.security);
  const setPassword = useAction(api.account.setPassword);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (security === undefined || security === null) return null;

  const hasPassword = security.hasPassword;
  const problems = passwordProblems(next);
  const mismatch = confirm.length > 0 && next !== confirm;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    if (problems.length > 0) {
      setError(`Password needs ${problems.join(", ")}.`);
      return;
    }
    if (next !== confirm) {
      setError("Those passwords don't match.");
      return;
    }

    setPending(true);
    try {
      await setPassword({
        currentPassword: hasPassword ? current : undefined,
        newPassword: next,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success(
        hasPassword
          ? "Password changed. Other devices have been signed out."
          : "Password set. You can now sign in with your email and password.",
      );
    } catch (err) {
      setError(friendlyAuthError(err, "We couldn't update your password."));
    } finally {
      setPending(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="flex w-full flex-col rounded-xl border border-border bg-card elev-1"
    >
      <div className="flex w-full flex-col gap-4 p-5">
        <div className="flex flex-col gap-1">
          <h3 className="font-display text-base font-semibold tracking-tight text-foreground">
            {hasPassword ? "Change password" : "Set a password"}
          </h3>
          <p className="text-sm leading-relaxed text-text-secondary">
            {hasPassword
              ? "Choose a new password. Signing in on your other devices will be required again."
              : "You sign in with a one-time email code. Add a password to sign in with one directly."}
          </p>
        </div>

        {hasPassword && (
          <Input
            type="password"
            autoComplete="current-password"
            placeholder="Current password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            aria-label="Current password"
            className="w-full bg-transparent sm:w-80"
          />
        )}
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="New password"
          required
          value={next}
          onChange={(e) => setNext(e.target.value)}
          aria-label="New password"
          // w-full sm:w-80 — three stacked 320px fields in a card with about
          // 295px of inner width overflowed it by 25px at 375px. The
          // placeholder was also the only label, and placeholders vanish on
          // input, so each field now carries an explicit name too.
          className="w-full bg-transparent sm:w-80"
        />
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="Confirm new password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-label="Confirm new password"
          className={`w-full bg-transparent sm:w-80 ${mismatch ? "border-destructive focus-visible:ring-destructive" : ""}`}
        />

        {next.length > 0 && problems.length > 0 && (
          <p className="text-sm text-text-secondary">
            Needs {problems.join(", ")}.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>

      <div className="flex w-full flex-wrap items-center justify-between gap-3 rounded-b-xl border-t border-border bg-surface px-5 py-3.5">
        <p className="text-sm text-text-secondary">
          At least 8 characters, with upper case, lower case and a number.
        </p>
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Saving…" : hasPassword ? "Change password" : "Set password"}
        </Button>
      </div>
    </form>
  );
}
