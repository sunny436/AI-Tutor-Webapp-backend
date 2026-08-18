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
      className="flex w-full flex-col items-start rounded-lg border border-border bg-card"
    >
      <div className="flex w-full flex-col gap-4 rounded-lg p-6">
        <div className="flex flex-col gap-2">
          <h2 className="text-xl font-medium text-primary">
            {hasPassword ? "Change password" : "Set a password"}
          </h2>
          <p className="text-sm font-normal text-primary/60">
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
            className="w-80 bg-transparent"
          />
        )}
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="New password"
          required
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className="w-80 bg-transparent"
        />
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="Confirm new password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={`w-80 bg-transparent ${mismatch ? "border-destructive focus-visible:ring-destructive" : ""}`}
        />

        {next.length > 0 && problems.length > 0 && (
          <p className="text-sm text-primary/60">Needs {problems.join(", ")}.</p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive dark:text-destructive-foreground">
            {error}
          </p>
        )}
      </div>

      <div className="flex min-h-14 w-full items-center justify-between rounded-lg rounded-t-none border-t border-border bg-secondary px-6 dark:bg-card">
        <p className="text-sm font-normal text-primary/60">
          At least 8 characters, with upper case, lower case and a number.
        </p>
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Saving…" : hasPassword ? "Change password" : "Set password"}
        </Button>
      </div>
    </form>
  );
}
