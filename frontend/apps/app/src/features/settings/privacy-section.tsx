"use client";

import { Badge } from "@v1/ui/badge";
import { Button } from "@v1/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@v1/ui/dialog";
import { Input } from "@v1/ui/input";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { Laptop } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { useUser } from "@/components/user-context";
import { useStores } from "@/features/chat/chat-context";
import { deleteAccount, getMe, revokeOtherSessions } from "@/lib/api/auth";
import { ApiError, describeError } from "@/lib/api/errors";
import { listSessions, revokeSession } from "@/lib/api/identity";
import { PASSWORD_MAX, PASSWORD_MIN, type SessionInfo } from "@/lib/api/types";
import { cacheAttributes } from "@/lib/appearance";
import { authClient } from "@/lib/auth/client";
import { relativeTime, shortDate } from "@/lib/time";
import { Field, SectionHeading, SettingsCard } from "./primitives";
import type { SectionProps } from "./section-view";
import { useUnsavedChanges } from "./use-unsaved-changes";

function wrongPassword(error: unknown): boolean {
  return error instanceof ApiError && error.code === "invalid_credentials";
}

function needsFreshSignIn(error: unknown): boolean {
  return error instanceof ApiError && error.code === "reauth_required";
}

const SIGN_IN_AGAIN = "For your security, sign out and sign in again, then try within 15 minutes.";

/** The account's ways to sign in (Better Auth's accounts): a password, Google (its account row id). */
type Methods = { password: boolean; google: string | null } | null;

function useSignInMethods(): [Methods, () => Promise<void>] {
  const [methods, setMethods] = useState<Methods>(null);
  const load = useCallback(async () => {
    const { data } = await authClient.listAccounts();
    const accounts = data ?? [];
    setMethods({
      password: accounts.some((account) => account.providerId === "credential"),
      google: accounts.find((account) => account.providerId === "google")?.id ?? null,
    });
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return [methods, load];
}

function PasswordCard({ hasPassword, onSet }: { hasPassword: boolean; onSet: () => Promise<void> }) {
  const { user, setUser } = useUser();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useUnsavedChanges(Boolean(current || next || confirm));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (next.length < PASSWORD_MIN || next.length > PASSWORD_MAX) {
      setError(`Use ${PASSWORD_MIN}–${PASSWORD_MAX} characters.`);
      return;
    }
    if (next !== confirm) {
      setError("Those passwords don't match.");
      return;
    }
    setPending(true);
    try {
      if (hasPassword) {
        const { error: failed } = await authClient.changePassword({
          currentPassword: current,
          newPassword: next,
          revokeOtherSessions: true,
        });
        if (failed) {
          setError(
            failed.status === 429
              ? "Too many attempts. Please wait a few minutes and try again."
              : failed.code === "INVALID_PASSWORD"
                ? "Your current password isn't right."
                : "Something went wrong. Please try again.",
          );
          return;
        }
        toast.success("Password changed. Your other devices have been signed out.");
      } else {
        const response = await fetch("/api/account/password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ newPassword: next }),
        });
        if (response.status === 409) {
          const { error: body } = (await response.json().catch(() => ({}))) as { error?: { code?: string } };
          setError(body?.code === "reauth_required" ? SIGN_IN_AGAIN : "This account already has a password.");
          return;
        }
        if (!response.ok) {
          setError("Something went wrong. Please try again.");
          return;
        }
        toast.success("Password set. Your other devices have been signed out.");
        await onSet();
      }
      setCurrent("");
      setNext("");
      setConfirm("");
      setUser(await getMe()); // for the new "last changed" date
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <SettingsCard
        title={hasPassword ? "Change password" : "Set a password"}
        description={
          hasPassword ? (
            <>
              {user.passwordChangedAt
                ? `Last changed ${relativeTime(user.passwordChangedAt)} (${shortDate(user.passwordChangedAt)}).`
                : "Not changed since you joined."}{" "}
              You'll stay signed in here; other devices will be signed out.
            </>
          ) : (
            "You sign in with Google or an email code. Add a password to sign in with it too. It needs a sign-in in the last 15 minutes."
          )
        }
        footer={
          <Button type="submit" size="sm" disabled={pending}>
            {pending ? "Saving…" : hasPassword ? "Change password" : "Set password"}
          </Button>
        }
      >
        {hasPassword && (
          <Field label="Current password">
            {(props) => (
              <Input
                {...props}
                className="w-full sm:max-w-[20rem]"
                type="password"
                autoComplete="current-password"
                required
                maxLength={PASSWORD_MAX}
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="New password" hint={`${PASSWORD_MIN}–${PASSWORD_MAX} characters.`}>
          {(props) => (
            <Input
              {...props}
              className="w-full sm:max-w-[20rem]"
              type="password"
              autoComplete="new-password"
              required
              minLength={PASSWORD_MIN}
              maxLength={PASSWORD_MAX}
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          )}
        </Field>
        <Field label="Confirm new password">
          {(props) => (
            <Input
              {...props}
              className="w-full sm:max-w-[20rem]"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          )}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </SettingsCard>
    </form>
  );
}

function DevicesCard() {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setSessions((await listSessions()).items);
    } catch (caught) {
      setLoadError(describeError(caught).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const signOut = async (session: SessionInfo) => {
    setBusy(session.id);
    try {
      await revokeSession(session.id);
      setSessions((list) => list?.filter((item) => item.id !== session.id) ?? null);
      toast.success(`Signed out ${session.device}.`);
    } catch (caught) {
      // Already gone (signed out elsewhere, or expired): the list was simply out of date.
      if (caught instanceof ApiError && caught.code === "not_found") await load();
      else toast.error(describeError(caught).message);
    } finally {
      setBusy(null);
    }
  };

  const signOutOthers = async () => {
    setBusy("others");
    try {
      await revokeOtherSessions();
      toast.success("Signed out of all other devices.");
      await load();
    } catch (caught) {
      toast.error(describeError(caught).message);
    } finally {
      setBusy(null);
    }
  };

  const others = sessions?.filter((session) => !session.current).length ?? 0;

  return (
    <SettingsCard
      title="Signed-in devices"
      description="Where your account is signed in. Only the network is shown, never your full address."
      footer={
        <Button type="button" size="sm" variant="outline" onClick={signOutOthers} disabled={busy !== null || others === 0}>
          {busy === "others" ? "Signing out…" : "Sign out other devices"}
        </Button>
      }
    >
      {loadError ? (
        <div className="text-sm text-text-secondary">
          <p>{loadError}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="focus-ring mt-1 rounded font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </div>
      ) : sessions === null ? (
        <SkeletonGroup label="Loading devices" className="space-y-2">
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-12 w-full rounded-xl" />
        </SkeletonGroup>
      ) : (
        <ul className="divide-y divide-border">
          {sessions.map((session) => (
            <li key={session.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
              <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-text-secondary">
                <Laptop className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-foreground">
                  {session.device}
                  {session.current && <Badge variant="brand">This device</Badge>}
                </p>
                <p className="text-xs text-text-secondary">
                  {session.current ? "Active now" : `Active ${relativeTime(session.lastSeenAt)}`}
                  {session.ipMasked && ` · ${session.ipMasked}`}
                </p>
              </div>
              {!session.current && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => signOut(session)}
                  disabled={busy !== null}
                  aria-label={`Sign out ${session.device}, active ${relativeTime(session.lastSeenAt)}`}
                >
                  {busy === session.id ? "Signing out…" : "Sign out"}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </SettingsCard>
  );
}

function GoogleCard({ accountId, onChange }: { accountId: string | null; onChange: () => Promise<void> }) {
  const connected = accountId !== null;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(() => {
    // Google sends the student back here; a link it refused arrives as ?error=.
    if (typeof window === "undefined") return null;
    const code = new URLSearchParams(window.location.search).get("error");
    if (!code) return null;
    return code.toLowerCase().includes("email")
      ? "That Google account uses a different email address. Connect the Google account for this email."
      : "Google didn't connect. Please try again.";
  });

  const connect = async () => {
    setError(null);
    setPending(true);
    const { error: failed } = await authClient.linkSocial({
      provider: "google",
      callbackURL: "/settings/privacy",
      errorCallbackURL: "/settings/privacy",
    });
    if (failed) {
      setPending(false);
      setError("Google didn't connect. Please try again.");
    }
  };

  const disconnect = async () => {
    setError(null);
    setPending(true);
    try {
      if (!accountId) return;
      const { error: failed } = await authClient.unlinkAccount({ accountId });
      if (failed) {
        setError(
          failed.code === "FAILED_TO_UNLINK_LAST_ACCOUNT"
            ? "Google is how you sign in. Set a password first, then disconnect it."
            : failed.code === "SESSION_NOT_FRESH" || failed.status === 403
              ? SIGN_IN_AGAIN
              : "Something went wrong. Please try again.",
        );
        return;
      }
      toast.success("Google disconnected.");
      await onChange();
    } finally {
      setPending(false);
    }
  };

  return (
    <SettingsCard
      title="Google"
      description={
        connected
          ? "You can sign in with your Google account."
          : "Sign in with your Google account too. It must use the same email address as this account."
      }
      footer={
        connected ? (
          <Button type="button" size="sm" variant="outline" onClick={() => void disconnect()} disabled={pending}>
            {pending ? "Disconnecting…" : "Disconnect Google"}
          </Button>
        ) : (
          <Button type="button" size="sm" variant="outline" onClick={() => void connect()} disabled={pending}>
            {pending ? "Opening Google…" : "Connect Google"}
          </Button>
        )
      }
    >
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </SettingsCard>
  );
}

function DeleteAccountCard({ hasPassword }: { hasPassword: boolean }) {
  const { chat } = useStores();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();

  const confirmDelete = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await deleteAccount(hasPassword ? { password } : {});
      chat.reset();
      cacheAttributes(null);
      window.location.assign("/login?reason=deleted");
    } catch (caught) {
      setPending(false);
      setError(
        wrongPassword(caught)
          ? "That password isn't right."
          : needsFreshSignIn(caught)
            ? SIGN_IN_AGAIN
            : describeError(caught).message,
      );
    }
  };

  return (
    <SettingsCard
      title="Delete account"
      titleAs="h4"
      tone="danger"
      description="Permanently deletes your account and everything in it: chats, settings, progress and your photo. This cannot be undone."
      footer={
        <Button type="button" size="sm" variant="destructive" onClick={() => setOpen(true)}>
          Delete account
        </Button>
      }
    >
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) {
            setPassword("");
            setError(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <form onSubmit={confirmDelete}>
            <DialogHeader>
              <DialogTitle>Delete your account?</DialogTitle>
              <DialogDescription>
                {hasPassword
                  ? "Enter your password to confirm. Everything in your account will be deleted."
                  : "Everything in your account will be deleted. You must have signed in within the last 15 minutes."}
              </DialogDescription>
            </DialogHeader>
            <div className="my-4">
              {hasPassword && (
                <>
                  <label htmlFor={fieldId} className="text-sm font-bold text-foreground">
                    Password
                  </label>
                  <Input
                    id={fieldId}
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </>
              )}
              {error && (
                <p role="alert" className="mt-2 text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
            <DialogFooter className="gap-2 sm:gap-2">
              <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={pending}>
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={pending || (hasPassword && !password)}>
                {pending ? "Deleting…" : "Delete account"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </SettingsCard>
  );
}

export function PrivacySection({ googleEnabled }: SectionProps) {
  const [methods, reload] = useSignInMethods();
  return (
    <>
      <SectionHeading
        title="Privacy & Security"
        description="How you sign in, the devices signed in to your account, and deleting it."
      />
      <div className="flex flex-col gap-4">
        {methods === null ? (
          <SkeletonGroup label="Loading sign-in methods" className="space-y-2">
            <Skeleton className="h-40 w-full rounded-2xl" />
          </SkeletonGroup>
        ) : (
          <>
            <PasswordCard hasPassword={methods.password} onSet={reload} />
            {(googleEnabled || methods.google) && <GoogleCard accountId={methods.google} onChange={reload} />}
          </>
        )}
        <DevicesCard />
        <h3 className="mt-4 font-display text-lg font-bold tracking-tight text-destructive">Danger zone</h3>
        <DeleteAccountCard hasPassword={methods?.password ?? true} />
      </div>
    </>
  );
}
