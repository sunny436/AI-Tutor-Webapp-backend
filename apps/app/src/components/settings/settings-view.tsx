"use client";

import { Button } from "@v1/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@v1/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@v1/ui/dialog";
import { Input } from "@v1/ui/input";
import { type FormEvent, useId, useState } from "react";
import { toast } from "sonner";

import { useStores } from "@/features/chat/chat-context";
import { changePassword, deleteAccount, revokeOtherSessions, updateMe } from "@/lib/api/auth";
import { ApiError, describeError } from "@/lib/api/errors";
import { DISPLAY_NAME_MAX, PASSWORD_MAX, PASSWORD_MIN } from "@/lib/api/types";
import { ThemeSwitcher } from "../theme-switcher";
import { useUser } from "../user-context";
import { SettingsSection } from "./settings-section";

function LabeledInput({
  label,
  hint,
  ...props
}: React.ComponentProps<typeof Input> & { label: string; hint?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
      </label>
      <Input id={id} className="w-full sm:w-80" {...props} />
      {hint && <p className="text-2xs text-text-secondary">{hint}</p>}
    </div>
  );
}

function wrongPassword(error: unknown): boolean {
  return error instanceof ApiError && error.code === "invalid_credentials";
}

function Profile() {
  const { user, setUser } = useUser();
  const [name, setName] = useState(user.displayName ?? "");
  const [pending, setPending] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    try {
      setUser(await updateMe({ displayName: name.trim() || null }));
      toast.success("Name saved.");
    } catch (error) {
      toast.error(describeError(error).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={save}>
      <Card>
      <CardHeader>
        <CardTitle as="h3">Profile</CardTitle>
        <CardDescription>Signed in as {user.email}.</CardDescription>
      </CardHeader>
      <CardContent>
        <LabeledInput
          label="Display name"
          value={name}
          maxLength={DISPLAY_NAME_MAX}
          autoComplete="name"
          onChange={(event) => setName(event.target.value)}
        />
      </CardContent>
      <CardFooter className="justify-end rounded-b-xl bg-surface">
        <Button type="submit" size="sm" disabled={pending || name.trim() === (user.displayName ?? "")}>
          {pending ? "Saving…" : "Save"}
        </Button>
      </CardFooter>
      </Card>
    </form>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    } catch (caught) {
      setError(wrongPassword(caught) ? "Your current password isn't right." : describeError(caught).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <Card>
      <CardHeader>
        <CardTitle as="h3">Change password</CardTitle>
        <CardDescription>You'll stay signed in here; other devices will be signed out.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <LabeledInput
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={PASSWORD_MAX}
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <LabeledInput
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN}
          maxLength={PASSWORD_MAX}
          hint={`${PASSWORD_MIN}–${PASSWORD_MAX} characters.`}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        <LabeledInput
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
      <CardFooter className="justify-end rounded-b-xl bg-surface">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Saving…" : "Change password"}
        </Button>
      </CardFooter>
      </Card>
    </form>
  );
}

function Sessions() {
  const [pending, setPending] = useState(false);
  const signOutOthers = async () => {
    setPending(true);
    try {
      await revokeOtherSessions();
      toast.success("Signed out of all other devices.");
    } catch (error) {
      toast.error(describeError(error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h3">Other devices</CardTitle>
        <CardDescription>Sign out everywhere except this browser.</CardDescription>
      </CardHeader>
      <CardFooter className="justify-end rounded-b-xl bg-surface">
        <Button type="button" size="sm" variant="outline" onClick={signOutOthers} disabled={pending}>
          {pending ? "Signing out…" : "Sign out other devices"}
        </Button>
      </CardFooter>
    </Card>
  );
}

function DeleteAccount() {
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
      window.location.assign("/login?reason=deleted");
    } catch (caught) {
      setPending(false);
      setError(wrongPassword(caught) ? "That password isn't right." : describeError(caught).message);
    }
  };

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle as="h3">Delete account</CardTitle>
        <CardDescription>Permanently deletes your account and every chat in it. This cannot be undone.</CardDescription>
      </CardHeader>
      <CardFooter className="justify-end rounded-b-xl border-destructive/20 bg-destructive/10">
        <Button type="button" size="sm" variant="destructive" onClick={() => setOpen(true)}>
          Delete account
        </Button>
      </CardFooter>

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
              <DialogDescription>Enter your password to confirm. All of your chats will be deleted.</DialogDescription>
            </DialogHeader>
            <div className="py-4">
              <label htmlFor={fieldId} className="mb-1.5 block text-sm font-medium">
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
    </Card>
  );
}

export function SettingsView() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-6 sm:px-6 sm:py-8">
        <SettingsSection title="Account" description="Your name and sign-in.">
          <Profile />
          <Password />
          <Sessions />
        </SettingsSection>
        <SettingsSection title="Appearance" description="Light, dark, or follow your system.">
          <Card>
            <CardContent className="flex items-center justify-between gap-4 pt-6">
              <span className="text-sm text-foreground">Theme</span>
              <ThemeSwitcher />
            </CardContent>
          </Card>
        </SettingsSection>
        <SettingsSection title="Danger zone" tone="danger">
          <DeleteAccount />
        </SettingsSection>
      </div>
    </div>
  );
}
