"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@v1/ui/avatar";
import { Button } from "@v1/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@v1/ui/dialog";
import { Input } from "@v1/ui/input";
import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { useUser } from "@/components/user-context";
import { authClient } from "@/lib/auth/client";
import { ApiError, describeError } from "@/lib/api/errors";
import {
  AVATAR_MAX_BYTES,
  AVATAR_TYPES,
  avatarSrc,
  confirmEmailChange,
  removeAvatar,
  requestEmailChange,
  updateProfile,
  uploadAvatar,
} from "@/lib/api/identity";
import { CODE_LENGTH, DISPLAY_NAME_MAX, type ProfileValues, type User } from "@/lib/api/types";
import { deviceZone, supportedZones } from "@/lib/time-zones";
import { Field, Notice, SectionHeading, SettingsCard } from "./primitives";
import { useUnsavedChanges } from "./use-unsaved-changes";

const MAX_MB = Math.round(AVATAR_MAX_BYTES / (1024 * 1024));

function photoError(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.reasonFor("image");
    if (reason === "too_small") return "Use a photo at least 32 pixels wide and tall.";
    if (reason === "too_many_pixels") return "That image is very large. Use a smaller photo.";
    if (reason === "type_mismatch") return "That file isn't the kind of image it says it is.";
    if (reason === "unreadable" || reason === "empty") return "That file couldn't be read as an image.";
    if (error.code === "unsupported_media_type") return "Use a JPEG, PNG or WebP image.";
    if (error.code === "payload_too_large") return `Use a photo smaller than ${MAX_MB} MB.`;
  }
  return describeError(error).message;
}

function initial(user: User): string {
  return (user.displayName || user.email).charAt(0).toUpperCase();
}

function PhotoCard() {
  const { user, setUser } = useUser();
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const busy = progress !== null || removing;
  const src = preview ?? avatarSrc(user);

  const choose = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // choosing the same file again still fires
    if (!file) return;
    setError(null);
    if (!AVATAR_TYPES.includes(file.type)) {
      setError("Use a JPEG, PNG or WebP image.");
      return;
    }
    if (file.size > AVATAR_MAX_BYTES) {
      setError(`Use a photo smaller than ${MAX_MB} MB.`);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    setProgress(0);
    try {
      setUser(await uploadAvatar(file, { onProgress: setProgress }));
      toast.success("Photo updated.");
    } catch (caught) {
      setError(photoError(caught));
    } finally {
      URL.revokeObjectURL(url);
      setPreview(null);
      setProgress(null);
    }
  };

  const remove = async () => {
    setError(null);
    setRemoving(true);
    try {
      setUser(await removeAvatar());
      toast.success("Photo removed.");
    } catch (caught) {
      setError(describeError(caught).message);
    } finally {
      setRemoving(false);
    }
  };

  return (
    <SettingsCard
      title="Photo"
      description={`JPEG, PNG or WebP, up to ${MAX_MB} MB. It's cropped to a square and stored without its location or camera details.`}
    >
      <div className="flex flex-wrap items-center gap-4">
        <Avatar className="h-20 w-20 text-2xl">
          {src && <AvatarImage src={src} alt="" />}
          <AvatarFallback className="text-2xl font-bold">{initial(user)}</AvatarFallback>
        </Avatar>
        <div className="flex flex-wrap gap-2">
          <input
            ref={input}
            type="file"
            accept={AVATAR_TYPES.join(",")}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={choose}
          />
          <Button type="button" size="sm" onClick={() => input.current?.click()} disabled={busy}>
            {user.avatar ? "Change photo" : "Upload photo"}
          </Button>
          {user.avatar && (
            <Button type="button" size="sm" variant="outline" onClick={remove} disabled={busy}>
              {removing ? "Removing…" : "Remove photo"}
            </Button>
          )}
        </div>
      </div>
      {progress !== null && (
        <div
          role="progressbar"
          aria-label="Uploading photo"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        >
          <div className="h-full bg-brand transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </SettingsCard>
  );
}

function valuesOf(user: User): ProfileValues {
  return { displayName: user.displayName ?? "", timezone: user.timezone ?? "" };
}

function NameAndZoneCard() {
  const { user, setUser } = useUser();
  const [base, setBase] = useState(() => ({ values: valuesOf(user), version: user.profileVersion }));
  const [draft, setDraft] = useState(base.values);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [errors, setErrors] = useState<{ displayName?: string; timezone?: string }>({});
  const [zones, setZones] = useState<string[]>([]);
  const [detected, setDetected] = useState<string | null>(null);
  const dirty = draft.displayName.trim() !== base.values.displayName || draft.timezone !== base.values.timezone;
  useUnsavedChanges(dirty);

  // The zone list comes from this browser, so it is read after mount (the server's may differ).
  useEffect(() => {
    setZones(supportedZones());
    setDetected(deviceZone());
  }, []);

  // Another part of Settings changed the user (an email change moves the version on).
  // Follows the user only while nothing is typed.
  useEffect(() => {
    if (!dirty) {
      setBase({ values: valuesOf(user), version: user.profileVersion });
      setDraft(valuesOf(user));
    }
  }, [user]);

  const options = useMemo(() => {
    const all = new Set(zones);
    for (const zone of [draft.timezone, base.values.timezone]) if (zone) all.add(zone);
    return [...all].sort();
  }, [zones, draft.timezone, base.values.timezone]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (pending || !dirty) return;
    setErrors({});
    setNotice(null);
    const name = draft.displayName.trim();
    const set: Partial<ProfileValues> = {};
    const reset: (keyof ProfileValues)[] = [];
    if (name !== base.values.displayName) {
      if (name) set.displayName = name;
      else reset.push("displayName");
    }
    if (draft.timezone !== base.values.timezone) {
      if (draft.timezone) set.timezone = draft.timezone;
      else reset.push("timezone");
    }
    setPending(true);
    try {
      const updated = await updateProfile({ version: base.version, set, reset });
      setUser(updated);
      setBase({ values: valuesOf(updated), version: updated.profileVersion });
      setDraft(valuesOf(updated));
      toast.success("Profile saved.");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "version_conflict" && caught.current) {
        const current = caught.current as User;
        setUser(current);
        setBase({ values: valuesOf(current), version: current.profileVersion });
        setNotice("Your profile was just changed somewhere else. Your edits are still here: check them and save again.");
      } else if (caught instanceof ApiError && caught.reasonFor("set.timezone")) {
        setErrors({ timezone: "That time zone can't be used. Choose another." });
      } else if (caught instanceof ApiError && caught.reasonFor("set.displayName")) {
        setErrors({ displayName: `Use 1–${DISPLAY_NAME_MAX} characters.` });
      } else {
        toast.error(describeError(caught).message);
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={save}>
      <SettingsCard
        title="Name and time zone"
        description="Your time zone decides when your day starts for progress and when reminders arrive."
        footer={
          <>
            {dirty && (
              <Button type="button" size="sm" variant="ghost" onClick={() => setDraft(base.values)} disabled={pending}>
                Cancel
              </Button>
            )}
            <Button type="submit" size="sm" disabled={pending || !dirty}>
              {pending ? "Saving…" : "Save"}
            </Button>
          </>
        }
      >
        {notice && <Notice tone="warning">{notice}</Notice>}
        <Field label="Display name" hint="Shown in the app. Leave it empty to use your email." error={errors.displayName}>
          {(props) => (
            <Input
              {...props}
              className="w-full sm:max-w-[20rem]"
              value={draft.displayName}
              maxLength={DISPLAY_NAME_MAX}
              autoComplete="name"
              onChange={(event) => setDraft({ ...draft, displayName: event.target.value })}
            />
          )}
        </Field>
        <Field
          label="Time zone"
          error={errors.timezone}
          hint={
            detected && detected !== draft.timezone ? (
              <button
                type="button"
                className="focus-ring rounded font-medium text-brand underline underline-offset-2"
                onClick={() => setDraft({ ...draft, timezone: detected })}
              >
                Use this device's time zone ({detected})
              </button>
            ) : undefined
          }
        >
          {(props) => (
            <select
              {...props}
              value={draft.timezone}
              onChange={(event) => setDraft({ ...draft, timezone: event.target.value })}
              className="focus-field h-10 w-full rounded-xl border border-input bg-card px-3 text-base sm:max-w-[20rem] sm:text-sm"
            >
              <option value="">Not set</option>
              {options.map((zone) => (
                <option key={zone} value={zone}>
                  {zone.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          )}
        </Field>
      </SettingsCard>
    </form>
  );
}

type EmailStep = { step: "address" } | { step: "code"; newEmail: string };

function EmailCard() {
  const { user, setUser } = useUser();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EmailStep>({ step: "address" });
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // An account without a password (Google, or email codes only) confirms by a recent sign-in.
  const [hasPassword, setHasPassword] = useState(true);

  useEffect(() => {
    if (!open) return;
    void authClient.listAccounts().then(({ data }) => {
      if (data) setHasPassword(data.some((account) => account.providerId === "credential"));
    });
  }, [open]);

  const reset = () => {
    setState({ step: "address" });
    setNewEmail("");
    setPassword("");
    setCode("");
    setError(null);
  };

  const sendCode = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const address = newEmail.trim();
      await requestEmailChange(hasPassword ? { newEmail: address, password } : { newEmail: address });
      setPassword("");
      setState({ step: "code", newEmail: address });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "invalid_credentials") setError("That password isn't right.");
      else if (caught instanceof ApiError && caught.code === "reauth_required")
        setError("For your security, sign out and sign in again, then try within 15 minutes.");
      else if (caught instanceof ApiError && caught.reasonFor("newEmail") === "unchanged")
        setError("That's already your email address.");
      else setError(describeError(caught).message);
    } finally {
      setPending(false);
    }
  };

  const confirm = async (event: FormEvent) => {
    event.preventDefault();
    if (state.step !== "code") return;
    setError(null);
    setPending(true);
    try {
      const updated = await confirmEmailChange({ newEmail: state.newEmail, code: code.trim() });
      setUser(updated);
      setOpen(false);
      reset();
      toast.success(`Your email is now ${updated.email}. Your other devices were signed out.`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "invalid_code") setError("That code is wrong or has expired.");
      else if (caught instanceof ApiError && caught.code === "email_unavailable")
        setError("That address was just taken by another account. Use a different one.");
      else setError(describeError(caught).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <SettingsCard
      title="Email"
      description={
        <>
          You sign in with <span className="font-semibold text-foreground">{user.email}</span>.
        </>
      }
      footer={
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          Change email
        </Button>
      }
    >
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) reset();
        }}
      >
        <DialogContent className="sm:max-w-md">
          {state.step === "address" ? (
            <form onSubmit={sendCode}>
              <DialogHeader>
                <DialogTitle>Change your email</DialogTitle>
                <DialogDescription>
                  We'll send a code to the new address. Your email changes only after you enter it.
                </DialogDescription>
              </DialogHeader>
              <div className="my-4 flex flex-col gap-4">
                <Field label="New email">
                  {(props) => (
                    <Input
                      {...props}
                      type="email"
                      required
                      autoComplete="email"
                      value={newEmail}
                      onChange={(event) => setNewEmail(event.target.value)}
                    />
                  )}
                </Field>
                {hasPassword && (
                  <Field label="Current password">
                    {(props) => (
                      <Input
                        {...props}
                        type="password"
                        required
                        autoComplete="current-password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                      />
                    )}
                  </Field>
                )}
                {error && (
                  <p role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                )}
              </div>
              <DialogFooter className="gap-2 sm:gap-2">
                <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={pending}>
                  Cancel
                </Button>
                <Button type="submit" disabled={pending || !newEmail || (hasPassword && !password)}>
                  {pending ? "Sending…" : "Send code"}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <form onSubmit={confirm}>
              <DialogHeader>
                <DialogTitle>Enter the code</DialogTitle>
                <DialogDescription>
                  If {state.newEmail} can be used, we've sent a {CODE_LENGTH}-digit code to it. It expires in 15
                  minutes.
                </DialogDescription>
              </DialogHeader>
              <div className="my-4 flex flex-col gap-4">
                <Field label="Code">
                  {(props) => (
                    <Input
                      {...props}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern={`\\d{${CODE_LENGTH}}`}
                      maxLength={CODE_LENGTH}
                      required
                      value={code}
                      onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
                    />
                  )}
                </Field>
                {error && (
                  <p role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                )}
              </div>
              <DialogFooter className="gap-2 sm:gap-2">
                <Button type="button" variant="outline" onClick={reset} disabled={pending}>
                  Use a different address
                </Button>
                <Button type="submit" disabled={pending || code.length !== CODE_LENGTH}>
                  {pending ? "Checking…" : "Change email"}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </SettingsCard>
  );
}

export function ProfileSection() {
  return (
    <>
      <SectionHeading title="Profile" description="How you appear in PadhAI, and the email you sign in with." />
      <div className="flex flex-col gap-4">
        <PhotoCard />
        <NameAndZoneCard />
        <EmailCard />
      </div>
    </>
  );
}
