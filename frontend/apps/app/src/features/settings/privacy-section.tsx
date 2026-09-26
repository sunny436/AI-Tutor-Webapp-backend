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
import { changePassword, deleteAccount, getMe, revokeOtherSessions } from "@/lib/api/auth";
import { ApiError, describeError } from "@/lib/api/errors";
import { listSessions, revokeSession } from "@/lib/api/identity";
import { PASSWORD_MAX, PASSWORD_MIN, type SessionInfo } from "@/lib/api/types";
import { cacheAttributes } from "@/lib/appearance";
import { relativeTime, shortDate } from "@/lib/time";
import { Field, SectionHeading, SettingsCard } from "./primitives";
import { useUnsavedChanges } from "./use-unsaved-changes";

function wrongPassword(error: unknown): boolean {
  return error instanceof ApiError && error.code === "invalid_credentials";
}

function PasswordCard() {
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
      await changePassword({ currentPassword: current, newPassword: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password changed. Your other devices have been signed out.");
      setUser(await getMe()); // for the new "last changed" date
    } catch (caught) {
      setError(wrongPassword(caught) ? "Your current password isn't right." : describeError(caught).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <SettingsCard
        title="Change password"
        description={
          <>
            {user.passwordChangedAt
              ? `Last changed ${relativeTime(user.passwordChangedAt)} (${shortDate(user.passwordChangedAt)}).`
              : "Not changed since you joined."}{" "}
            You'll stay signed in here; other devices will be signed out.
          </>
        }
        footer={
          <Button type="submit" size="sm" disabled={pending}>
            {pending ? "Saving…" : "Change password"}
          </Button>
        }
      >
        <Field label="Current password">
          {(props) => (
            <Input
              {...props}
              className="w-full sm:w-80"
              type="password"
              autoComplete="current-password"
              required
              maxLength={PASSWORD_MAX}
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          )}
        </Field>
        <Field label="New password" hint={`${PASSWORD_MIN}–${PASSWORD_MAX} characters.`}>
          {(props) => (
            <Input
              {...props}
              className="w-full sm:w-80"
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
              className="w-full sm:w-80"
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

function DeleteAccountCard() {
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
      await deleteAccount({ password });
      chat.reset();
      cacheAttributes(null);
      window.location.assign("/login?reason=deleted");
    } catch (caught) {
      setPending(false);
      setError(wrongPassword(caught) ? "That password isn't right." : describeError(caught).message);
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
              <DialogDescription>Enter your password to confirm. Everything in your account will be deleted.</DialogDescription>
            </DialogHeader>
            <div className="my-4">
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
              <Button type="submit" variant="destructive" disabled={pending || !password}>
                {pending ? "Deleting…" : "Delete account"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </SettingsCard>
  );
}

export function PrivacySection() {
  return (
    <>
      <SectionHeading
        title="Privacy & Security"
        description="Your password, the devices signed in to your account, and deleting it."
      />
      <div className="flex flex-col gap-4">
        <PasswordCard />
        <DevicesCard />
        <h3 className="mt-4 font-display text-lg font-bold tracking-tight text-destructive">Danger zone</h3>
        <DeleteAccountCard />
      </div>
    </>
  );
}
