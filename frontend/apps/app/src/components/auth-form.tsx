"use client";

import { Button } from "@v1/ui/button";
import { Eye, EyeOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { CODE_LENGTH, DISPLAY_NAME_MAX, PASSWORD_MAX, PASSWORD_MIN } from "@/lib/api/types";
import { authClient } from "@/lib/auth/client";
import { GoogleMark } from "./google-mark";

/**
 * Signing in and up, email codes and password reset, through Better Auth (lib/auth). The session
 * cookie is set by the server; nothing here ever holds a token. After signing in the student goes
 * back to `redirectTo`, which the page has already passed through `safeRedirect`.
 *
 * Steps:
 *   signIn    Google, or email + password, or "Email me a code"
 *   signUp    Google, or email (+ name) -> code -> password (an account exists only once its
 *             address is proven, so nobody can claim someone else's address)
 *   code      the 6-digit code (signs in, or creates the account)
 *   password  the new account's password (can be skipped: codes and Google still sign in)
 *   forgot -> reset
 */
export type AuthMode = "signIn" | "signUp" | "code" | "password" | "forgot" | "reset";

const RESEND_SECONDS = 30;

// 16 px below `sm`: iOS Safari zooms the page when a focused field is smaller,
// and the zoom does not undo itself.
const inputClass =
  "h-11 w-full rounded-xl border border-input bg-card px-3 text-base font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-text-secondary focus:border-brand focus:ring-4 focus:ring-brand/10 sm:text-sm";
const linkClass =
  "focus-ring rounded text-sm font-medium text-brand underline-offset-2 transition-colors hover:text-brand-hover hover:underline disabled:text-text-secondary disabled:no-underline";

const TITLES: Record<AuthMode, string> = {
  signIn: "Sign in",
  signUp: "Create your account",
  code: "Check your email",
  password: "Choose a password",
  forgot: "Reset your password",
  reset: "Choose a new password",
};

// Better Auth's codes in this app's own words (its message text is never shown).
const ERRORS: Record<string, string> = {
  INVALID_EMAIL_OR_PASSWORD: "That email and password don't match.",
  EMAIL_NOT_VERIFIED: "This address isn't confirmed yet. Sign in with an email code instead.",
  INVALID_OTP: "That code isn't right.",
  OTP_EXPIRED: "That code has expired. Send a new one.",
  TOO_MANY_ATTEMPTS: "Too many wrong codes. Send a new one.",
  INVALID_EMAIL: "Enter a valid email address.",
  PASSWORD_TOO_SHORT: `Passwords must be ${PASSWORD_MIN}–${PASSWORD_MAX} characters.`,
  PASSWORD_TOO_LONG: `Passwords must be ${PASSWORD_MIN}–${PASSWORD_MAX} characters.`,
};

export function authErrorMessage(error: { code?: string; status?: number } | null | undefined): string {
  if (error?.status === 429) return "Too many attempts. Please wait a few minutes and try again.";
  return (error?.code && ERRORS[error.code]) || "Something went wrong. Please try again.";
}

/** Google sign-in comes back to /login?error=<code> when it does not end in a session. */
export function oauthErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null;
  const key = code.toLowerCase().replace(/[\s-]+/g, "_");
  if (key === "access_denied") return "Google sign-in was cancelled.";
  if (key === "account_not_linked") {
    return "This email has an unfinished sign-up. Sign in with an email code first; you can then add Google in Settings.";
  }
  if (key.includes("email_not_verified")) {
    return "Google hasn't confirmed this email address. Sign in with an email code instead.";
  }
  if (/state|restart|invalid_code|no_code|callback/.test(key)) return "Google sign-in timed out. Please try again.";
  return "Google sign-in didn't work. Please try again, or use your email.";
}

function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string, hintId?: string) => ReactNode }) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-bold text-foreground">
        {label}
      </label>
      {children(id, hintId)}
      {hint && (
        <p id={hintId} className="text-xs text-text-secondary">
          {hint}
        </p>
      )}
    </div>
  );
}

export function AuthForm({
  initialMode,
  redirectTo,
  notice,
  googleEnabled = false,
  oauthError,
}: {
  initialMode: "signIn" | "signUp";
  redirectTo: string;
  notice?: string | null;
  googleEnabled?: boolean;
  oauthError?: string | null;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [creating, setCreating] = useState(initialMode === "signUp"); // the code step creates an account
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(oauthErrorMessage(oauthError));
  const [info, setInfo] = useState<string | null>(notice ?? null);
  const [cooldown, setCooldown] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstStep = useRef(true);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  // A new step replaces the form: move focus to its heading so a screen reader announces it.
  useEffect(() => {
    if (firstStep.current) {
      firstStep.current = false;
      return;
    }
    heading.current?.focus();
  }, [mode]);

  const go = (next: AuthMode, message: string | null = null) => {
    setMode(next);
    setError(null);
    setInfo(message);
    setCode("");
    setShowPassword(false);
    if (next !== "signIn") setPassword("");
  };

  const signedIn = () => {
    router.replace(redirectTo);
    router.refresh();
  };

  const run = (action: () => Promise<void>) => async (event?: FormEvent) => {
    event?.preventDefault();
    setError(null);
    setPending(true);
    try {
      await action();
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setPending(false);
    }
  };

  const sendCode = async (purpose: "sign-in" | "forget-password"): Promise<boolean> => {
    const { error: failed } =
      purpose === "sign-in"
        ? await authClient.emailOtp.sendVerificationOtp({ email: email.trim(), type: "sign-in" })
        : await authClient.emailOtp.requestPasswordReset({ email: email.trim() });
    if (failed) {
      setError(authErrorMessage(failed));
      return false;
    }
    setCooldown(RESEND_SECONDS);
    return true;
  };

  const startCode = (createAccount: boolean) =>
    run(async () => {
      if (!(await sendCode("sign-in"))) return;
      setCreating(createAccount);
      go("code", `If ${email.trim()} can be used, a ${CODE_LENGTH}-digit code is on its way.`);
    });

  const submitSignIn = run(async () => {
    const { error: failed } = await authClient.signIn.email({ email: email.trim(), password });
    if (failed) setError(authErrorMessage(failed));
    else signedIn();
  });

  const submitCode = run(async () => {
    const { error: failed } = await authClient.signIn.emailOtp({
      email: email.trim(),
      otp: code.trim(),
      ...(creating && name.trim() ? { name: name.trim() } : {}),
    });
    if (failed) setError(authErrorMessage(failed));
    else if (creating) go("password");
    else signedIn();
  });

  const submitPassword = run(async () => {
    const response = await fetch("/api/account/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ newPassword: password }),
    });
    // 409 password_already_set: the address already had an account with a password; the code
    // proved it is theirs, so they are simply signed in.
    if (response.ok || response.status === 409) signedIn();
    else setError(response.status === 422 ? ERRORS.PASSWORD_TOO_SHORT! : "Something went wrong. Please try again.");
  });

  const submitForgot = run(async () => {
    if (await sendCode("forget-password")) go("reset", `If ${email.trim()} has an account, a reset code is on its way.`);
  });

  const submitReset = run(async () => {
    const { error: failed } = await authClient.emailOtp.resetPassword({ email: email.trim(), otp: code.trim(), password });
    if (failed) {
      setError(authErrorMessage(failed));
      return;
    }
    // Every device was signed out; this one signs in with the new password.
    const signed = await authClient.signIn.email({ email: email.trim(), password });
    if (signed.error) go("signIn", "Password changed. Sign in with your new password.");
    else signedIn();
  });

  const withGoogle = run(async () => {
    const { error: failed } = await authClient.signIn.social({
      provider: "google",
      callbackURL: redirectTo,
      newUserCallbackURL: redirectTo,
      errorCallbackURL: "/login",
    });
    // On success the browser is already on its way to Google.
    if (failed) setError(oauthErrorMessage(failed.code ?? "failed"));
  });

  const resend = async () => {
    if (cooldown > 0 || pending || !email) return;
    setError(null);
    setPending(true);
    try {
      if (await sendCode(mode === "reset" ? "forget-password" : "sign-in")) setInfo(`New code sent to ${email.trim()}.`);
    } finally {
      setPending(false);
    }
  };

  const emailField = (
    <Field label="Email">
      {(id) => (
        <input
          id={id}
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
      )}
    </Field>
  );

  const passwordField = (label: string, kind: "current-password" | "new-password") => (
    <Field label={label} hint={kind === "new-password" ? `${PASSWORD_MIN}–${PASSWORD_MAX} characters.` : undefined}>
      {(id, hintId) => (
        <div className="relative">
          <input
            id={id}
            type={showPassword ? "text" : "password"}
            autoComplete={kind}
            required
            minLength={kind === "new-password" ? PASSWORD_MIN : undefined}
            maxLength={PASSWORD_MAX}
            aria-describedby={hintId}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={`${inputClass} pr-12`}
          />
          <button
            type="button"
            onClick={() => setShowPassword((shown) => !shown)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            className="focus-ring absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-xl text-text-secondary hover:text-foreground"
          >
            {showPassword ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
          </button>
        </div>
      )}
    </Field>
  );

  const codeField = (
    <Field label="Code" hint={`The ${CODE_LENGTH}-digit code from the email. It expires in 15 minutes.`}>
      {(id, hintId) => (
        <input
          id={id}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern={`\\d{${CODE_LENGTH}}`}
          maxLength={CODE_LENGTH}
          required
          aria-describedby={hintId}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          className={`${inputClass} font-mono tracking-[0.3em]`}
        />
      )}
    </Field>
  );

  const googleButton = googleEnabled ? (
    <>
      <button
        type="button"
        onClick={() => void withGoogle()}
        disabled={pending}
        className="focus-ring flex h-11 w-full items-center justify-center gap-3 rounded-xl border border-border bg-card px-4 text-sm font-semibold text-foreground transition-colors hover:bg-surface-2 disabled:opacity-60"
      >
        <GoogleMark />
        Continue with Google
      </button>
      <div className="flex items-center gap-3 text-xs text-text-secondary" aria-hidden>
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
    </>
  ) : null;

  const resendButton = (
    <button type="button" onClick={() => void resend()} disabled={cooldown > 0 || pending || !email} className={linkClass}>
      {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
    </button>
  );

  let lead: string;
  let body: ReactNode;
  let cta: string;
  let onSubmit: (event: FormEvent) => void;
  let footer: ReactNode;

  switch (mode) {
    case "signIn":
      lead = "Welcome back.";
      cta = "Sign in";
      onSubmit = submitSignIn;
      body = (
        <>
          {emailField}
          {passwordField("Password", "current-password")}
        </>
      );
      footer = (
        <>
          <button type="button" onClick={() => go("forgot")} className={linkClass}>
            Forgot password?
          </button>
          <button type="button" onClick={startCode(false)} disabled={pending || !email} className={linkClass}>
            Email me a code instead
          </button>
          <a href={`/signup${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`} className={linkClass}>
            Create an account
          </a>
        </>
      );
      break;
    case "signUp":
      lead = "We'll email you a code to confirm it's you.";
      cta = "Send code";
      onSubmit = startCode(true);
      body = (
        <>
          <Field label="Name (optional)">
            {(id) => (
              <input
                id={id}
                autoComplete="name"
                maxLength={DISPLAY_NAME_MAX}
                value={name}
                onChange={(event) => setName(event.target.value)}
                className={inputClass}
              />
            )}
          </Field>
          {emailField}
        </>
      );
      footer = (
        <a href={`/login${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`} className={linkClass}>
          Have an account? Sign in
        </a>
      );
      break;
    case "code":
      lead = `Enter the ${CODE_LENGTH}-digit code we sent to ${email.trim() || "your email"}.`;
      cta = creating ? "Create account" : "Sign in";
      onSubmit = submitCode;
      body = codeField;
      footer = (
        <>
          {resendButton}
          <button type="button" onClick={() => go(creating ? "signUp" : "signIn")} className={linkClass}>
            Use a different email
          </button>
        </>
      );
      break;
    case "password":
      lead = "Use it to sign in next time. You can also keep signing in with an email code.";
      cta = "Save password";
      onSubmit = submitPassword;
      body = passwordField("Password", "new-password");
      footer = (
        <button type="button" onClick={signedIn} className={linkClass}>
          Skip for now
        </button>
      );
      break;
    case "forgot":
      lead = "We'll email you a code to set a new one.";
      cta = "Send reset code";
      onSubmit = submitForgot;
      body = emailField;
      footer = (
        <>
          <button type="button" onClick={() => go("reset")} className={linkClass}>
            I have a code
          </button>
          <button type="button" onClick={() => go("signIn")} className={linkClass}>
            Back to sign in
          </button>
        </>
      );
      break;
    case "reset":
      lead = "Enter the code from your email and a new password. Every device will be signed out.";
      cta = "Set new password";
      onSubmit = submitReset;
      body = (
        <>
          {emailField}
          {codeField}
          {passwordField("New password", "new-password")}
        </>
      );
      footer = (
        <>
          {resendButton}
          <button type="button" onClick={() => go("signIn")} className={linkClass}>
            Back to sign in
          </button>
        </>
      );
      break;
  }

  return (
    <div className="w-full">
      <div className="mb-6">
        <h1 ref={heading} tabIndex={-1} className="font-display text-2xl font-black tracking-tight text-foreground outline-none">
          {TITLES[mode]}
        </h1>
        <p className="mt-1 text-sm text-text-secondary">{lead}</p>
      </div>
      <div className="flex flex-col gap-4">
        {(mode === "signIn" || mode === "signUp") && googleButton}
        <form onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={pending}>
          {body}
          <div aria-live="polite">
            {info && !error && (
              <p role="status" className="rounded-xl border border-info/20 bg-info-soft px-3 py-2 text-sm text-info">
                {info}
              </p>
            )}
          </div>
          {error && (
            <p role="alert" className="rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={pending} className="h-11 w-full">
            {pending ? "Please wait…" : cta}
          </Button>
        </form>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">{footer}</div>
    </div>
  );
}
