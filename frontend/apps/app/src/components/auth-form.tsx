"use client";

import { Button } from "@v1/ui/button";
import { useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useEffect, useId, useState } from "react";

import { forgotPassword, login, resendCode, resetPassword, signup, verifyEmail } from "@/lib/api/auth";
import { ApiError, describeError } from "@/lib/api/errors";
import { CODE_LENGTH, DISPLAY_NAME_MAX, PASSWORD_MAX, PASSWORD_MIN } from "@/lib/api/types";

export type AuthMode = "signIn" | "signUp" | "verify" | "forgot" | "reset";

const RESEND_COOLDOWN_SECONDS = 30;

// 16 px below `sm`: iOS Safari zooms the page when a focused field is smaller,
// and the zoom does not undo itself.
const inputClass =
  "h-11 w-full rounded-xl border border-input bg-surface px-3 text-base font-medium text-foreground outline-none transition-[border-color,background-color,box-shadow] placeholder:text-text-secondary focus:border-brand focus:bg-card focus:ring-4 focus:ring-brand/10 sm:h-11 sm:text-sm";

function Field({ label, children, hint }: { label: string; children: (id: string) => ReactNode; hint?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-bold text-foreground">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-2xs text-text-secondary">{hint}</p>}
    </div>
  );
}

const TITLES: Record<AuthMode, { title: string; lead: string }> = {
  signIn: { title: "Sign in", lead: "Welcome back." },
  signUp: { title: "Create your account", lead: "It takes a minute." },
  verify: { title: "Check your email", lead: "Enter the 6-digit code we sent you." },
  forgot: { title: "Reset your password", lead: "We'll email you a code." },
  reset: { title: "Choose a new password", lead: "Enter the code from your email and a new password." },
};

/**
 * Sign in, sign up, email verification and password reset against the chat API.
 *
 * The session is set by the BFF as an httpOnly cookie on success; nothing here
 * touches a token. After signing in, the user goes back to `redirectTo`, which
 * the page has already passed through `safeRedirect`.
 */
export function AuthForm({
  initialMode,
  redirectTo,
  notice,
}: {
  initialMode: "signIn" | "signUp";
  redirectTo: string;
  notice?: string | null;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(notice ?? null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const switchTo = (next: AuthMode, message: string | null = null) => {
    setMode(next);
    setError(null);
    setInfo(message);
    setCode("");
    if (next === "reset" || next === "signIn") setPassword("");
  };

  const signedIn = () => {
    router.replace(redirectTo);
    router.refresh();
  };

  const run = (action: () => Promise<void>) => async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await action();
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setPending(false);
    }
  };

  const messageFor = (caught: unknown): string => {
    const description = describeError(caught);
    if (caught instanceof ApiError && caught.code === "validation_error") {
      const fields = caught.fields?.map((field) => field.field) ?? [];
      if (fields.includes("password") || fields.includes("newPassword")) {
        return `Passwords must be ${PASSWORD_MIN}–${PASSWORD_MAX} characters.`;
      }
      if (fields.includes("email")) return "Enter a valid email address.";
    }
    return description.message;
  };

  const sendCode = async (purpose: "verify_email" | "reset_password") => {
    await resendCode({ email, purpose });
    setCooldown(RESEND_COOLDOWN_SECONDS);
  };

  const submitSignIn = run(async () => {
    try {
      await login({ email, password });
      signedIn();
    } catch (caught) {
      // Right password, unconfirmed address: send a fresh code and ask for it.
      if (caught instanceof ApiError && caught.code === "email_not_verified") {
        await sendCode("verify_email");
        switchTo("verify", `We've sent a new code to ${email}.`);
        return;
      }
      throw caught;
    }
  });

  const submitSignUp = run(async () => {
    await signup({ email, password, displayName });
    setCooldown(RESEND_COOLDOWN_SECONDS);
    // Always 202, whether or not the address can be registered: say so neutrally.
    switchTo("verify", `If ${email} can be registered, a 6-digit code is on its way.`);
  });

  const submitVerify = run(async () => {
    await verifyEmail({ email, code: code.trim() });
    signedIn();
  });

  const submitForgot = run(async () => {
    await forgotPassword({ email });
    setCooldown(RESEND_COOLDOWN_SECONDS);
    switchTo("reset", `If an account exists for ${email}, a reset code is on its way.`);
  });

  const submitReset = run(async () => {
    await resetPassword({ email, code: code.trim(), newPassword: password });
    signedIn();
  });

  const resend = async () => {
    if (cooldown > 0 || pending || !email) return;
    setError(null);
    try {
      await sendCode(mode === "reset" ? "reset_password" : "verify_email");
      setInfo(`New code sent to ${email}.`);
    } catch (caught) {
      setError(messageFor(caught));
    }
  };

  const emailField = (
    <Field label="Email">
      {(id) => (
        <input
          id={id}
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
      )}
    </Field>
  );

  const codeField = (
    <Field label="Code">
      {(id) => (
        <input
          id={id}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern={`\\d{${CODE_LENGTH}}`}
          maxLength={CODE_LENGTH}
          required
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          className={`${inputClass} font-mono tracking-[0.3em]`}
        />
      )}
    </Field>
  );

  const newPasswordField = (label: string) => (
    <Field label={label} hint={`${PASSWORD_MIN}–${PASSWORD_MAX} characters.`}>
      {(id) => (
        <input
          id={id}
          type="password"
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN}
          maxLength={PASSWORD_MAX}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={inputClass}
        />
      )}
    </Field>
  );

  const link = (label: string, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      className="focus-ring rounded text-sm font-medium text-brand underline-offset-2 transition-colors hover:text-brand-hover hover:underline"
    >
      {label}
    </button>
  );

  const resendButton = (
    <button
      type="button"
      onClick={resend}
      disabled={cooldown > 0 || pending || !email}
      className="focus-ring rounded text-sm font-medium text-brand underline-offset-2 transition-colors hover:text-brand-hover hover:underline disabled:text-text-secondary disabled:no-underline"
    >
      {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
    </button>
  );

  let form: ReactNode;
  let footer: ReactNode;
  let cta: string;
  let onSubmit: (event: FormEvent) => void;

  switch (mode) {
    case "signIn":
      cta = "Sign in";
      onSubmit = submitSignIn;
      form = (
        <>
          {emailField}
          <Field label="Password">
            {(id) => (
              <input
                id={id}
                type="password"
                autoComplete="current-password"
                required
                maxLength={PASSWORD_MAX}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className={inputClass}
              />
            )}
          </Field>
        </>
      );
      footer = (
        <>
          {link("Forgot password?", () => switchTo("forgot"))}
          <a
            href={`/signup${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`}
            className="focus-ring rounded text-sm font-medium text-brand underline-offset-2 transition-colors hover:text-brand-hover hover:underline"
          >
            Create an account
          </a>
        </>
      );
      break;
    case "signUp":
      cta = "Create account";
      onSubmit = submitSignUp;
      form = (
        <>
          <Field label="Name (optional)">
            {(id) => (
              <input
                id={id}
                autoComplete="name"
                maxLength={DISPLAY_NAME_MAX}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className={inputClass}
              />
            )}
          </Field>
          {emailField}
          {newPasswordField("Password")}
        </>
      );
      footer = (
        <>
          {link("I have a code", () => switchTo("verify"))}
          <a
            href={`/login${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`}
            className="focus-ring rounded text-sm font-medium text-brand underline-offset-2 transition-colors hover:text-brand-hover hover:underline"
          >
            Have an account? Sign in
          </a>
        </>
      );
      break;
    case "verify":
      cta = "Verify email";
      onSubmit = submitVerify;
      form = (
        <>
          {emailField}
          {codeField}
        </>
      );
      footer = (
        <>
          {resendButton}
          {link("Back to sign in", () => switchTo("signIn"))}
        </>
      );
      break;
    case "forgot":
      cta = "Send reset code";
      onSubmit = submitForgot;
      form = emailField;
      footer = (
        <>
          {link("I have a code", () => switchTo("reset"))}
          {link("Back to sign in", () => switchTo("signIn"))}
        </>
      );
      break;
    case "reset":
      cta = "Set new password";
      onSubmit = submitReset;
      form = (
        <>
          {emailField}
          {codeField}
          {newPasswordField("New password")}
        </>
      );
      footer = (
        <>
          {resendButton}
          {link("Back to sign in", () => switchTo("signIn"))}
        </>
      );
      break;
  }

  return (
    <div className="w-full">
      <div className="mb-6">
        <h1 className="font-display text-2xl font-black tracking-tight text-foreground">{TITLES[mode].title}</h1>
        <p className="mt-1 text-sm text-text-secondary">{TITLES[mode].lead}</p>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {form}
        {info && !error && (
          <p role="status" className="rounded-xl border border-info/20 bg-info-soft px-3 py-2 text-sm text-info">
            {info}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" disabled={pending} className="w-full">
          {pending ? "Please wait…" : cta}
        </Button>
      </form>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">{footer}</div>
    </div>
  );
}
