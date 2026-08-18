"use client";

import { AUTH_MESSAGES, friendlyAuthError, messageForReason, passwordProblems } from "@/lib/auth-errors";
import { useAuthActions } from "@convex-dev/auth/react";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { useAction } from "convex/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

type Mode = "signIn" | "signUp" | "verify" | "forgot" | "reset";

// `text-base` below `sm`, not `text-sm`: iOS Safari zooms the whole page when a
// focused input's font is under 16px, and the zoom does not undo itself — you
// land on the login screen and it is suddenly magnified with no way back.
// h-11 on touch matches the Button's own accessible target height.
const input =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-base outline-none transition-colors placeholder:text-text-secondary focus:border-brand/60 focus:ring-2 focus:ring-brand/20 sm:h-10 sm:text-sm";

const RESEND_COOLDOWN_SECONDS = 30;
const REMEMBER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;
const googleEnabled = process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true";

// Module-level (stable identity) — defining this inside AuthForm remounts inputs every
// keystroke, which steals focus after one character.
function Shell({
  onSubmit,
  cta,
  pending,
  error,
  info,
  children,
}: {
  onSubmit: (e: React.FormEvent) => void;
  cta: string;
  pending: boolean;
  error: string | null;
  info: string | null;
  children: React.ReactNode;
}) {
  return (
    // The width classes (w-72 / w-64) are load-bearing: e2e/auth-live.js scopes
    // its selectors to `form.w-72` and `form.w-64` to tell the password form
    // from the magic-code one, since both contain an input[type=email].
    <form className="flex w-72 max-w-full flex-col gap-3" onSubmit={onSubmit}>
      {children}
      {/* `font-mono` was hard-coded here, which is why every call to action in
          the app rendered in a monospace face and read as a developer stub. */}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "…" : cta}
      </Button>
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
      {info && <p className="text-xs text-muted-foreground">{info}</p>}
    </form>
  );
}

const Switch = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <button type="button" className="rounded text-xs text-text-secondary underline underline-offset-2 transition-colors hover:text-foreground" onClick={onClick}>
    {label}
  </button>
);

/**
 * "Remember me" is a per-user choice, but Convex Auth's cookie lifetime is a
 * middleware-level option. The middleware reads this flag per request and picks a
 * persistent or session-only cookie config accordingly (see `middleware.ts`).
 * It holds no secret — only the preference.
 */
function setRememberCookie(remember: boolean) {
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = remember
    ? `rememberMe=1; path=/; max-age=${REMEMBER_COOKIE_MAX_AGE}; samesite=lax${secure}`
    : `rememberMe=0; path=/; samesite=lax${secure}`;
}

/** Only ever follow same-origin, non-protocol-relative paths. */
function safeRedirect(target: string | null): string {
  if (!target || !target.startsWith("/") || target.startsWith("//")) return "/";
  return target;
}

export function AuthForm() {
  const router = useRouter();
  const { signIn } = useAuthActions();
  const preflightSignIn = useAction(api.authStatus.preflightSignIn);
  const preflightSignUp = useAction(api.authStatus.preflightSignUp);
  const preflightReset = useAction(api.authStatus.preflightReset);

  const [mode, setMode] = useState<Mode>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  // Read from `window` rather than `useSearchParams`, which would force this whole
  // tree into a Suspense boundary / client-side bailout just to read one param.
  const redirectTo = useRef("/");
  useEffect(() => {
    redirectTo.current = safeRedirect(
      new URLSearchParams(window.location.search).get("redirect"),
    );
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const finish = useCallback(() => {
    setRememberCookie(remember);
    // `refresh` re-runs the server layout so the new cookie is picked up before paint.
    router.replace(redirectTo.current);
    router.refresh();
  }, [remember, router]);

  /**
   * `fallback` describes what the user was attempting. It matters because a
   * rejected code reaches us as a bare TypeError — Convex Auth's proxy discards
   * the server's reason — so the caller's context is the only accurate
   * information available at that point.
   */
  const run =
    (fn: () => Promise<void>, fallback?: string) => async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setPending(true);
      try {
        await fn();
      } catch (err) {
        setError(friendlyAuthError(err, fallback));
      } finally {
        setPending(false);
      }
    };

  const goToVerify = (message: string) => {
    setCode("");
    setInfo(message);
    setMode("verify");
    setCooldown(RESEND_COOLDOWN_SECONDS);
  };

  const submitSignIn = run(async () => {
    // The pre-flight is what makes precise errors possible: `signIn` failures are
    // swallowed by Convex Auth's proxy before they reach the browser.
    const check = await preflightSignIn({ email, password });
    if (!check.ok && check.reason !== "unverified") {
      setError(messageForReason(check.reason));
      return;
    }
    setRememberCookie(remember);
    const result = await signIn("password", { email, password, flow: "signIn" });
    if (result?.signingIn) {
      finish();
      return;
    }
    // Correct credentials on an unconfirmed address: the provider has just emailed
    // a fresh code instead of opening a session.
    goToVerify(`We've sent a verification code to ${email}.`);
  });

  const submitSignUp = run(async () => {
    const problems = passwordProblems(password);
    if (problems.length > 0) {
      setError(`Password needs ${problems.join(", ")}.`);
      return;
    }
    const check = await preflightSignUp({ email });
    if (!check.ok) {
      setError(messageForReason(check.reason));
      return;
    }
    setRememberCookie(remember);
    const result = await signIn("password", { email, password, flow: "signUp" });
    if (result?.signingIn) {
      finish();
      return;
    }
    goToVerify(`Account created. Enter the code we sent to ${email}.`);
  });

  const submitVerify = run(async () => {
    const result = await signIn("password", {
      email,
      code: code.trim(),
      flow: "email-verification",
    });
    if (result?.signingIn) {
      finish();
      return;
    }
    setError(AUTH_MESSAGES.invalid_code);
  }, AUTH_MESSAGES.invalid_code);

  const submitForgot = run(async () => {
    const { send } = await preflightReset({ email });
    // Only call `signIn` when an account exists — otherwise it throws. The message
    // below is identical either way, so this never reveals whether it does.
    if (send) await signIn("password", { email, flow: "reset" });
    setCode("");
    setNewPassword("");
    setInfo(`If an account exists for ${email}, we've sent a reset code.`);
    setMode("reset");
    setCooldown(RESEND_COOLDOWN_SECONDS);
  });

  const submitReset = run(async () => {
    const problems = passwordProblems(newPassword);
    if (problems.length > 0) {
      setError(`Password needs ${problems.join(", ")}.`);
      return;
    }
    setRememberCookie(remember);
    const result = await signIn("password", {
      email,
      code: code.trim(),
      newPassword,
      flow: "reset-verification",
    });
    if (result?.signingIn) {
      finish();
      return;
    }
    setError(AUTH_MESSAGES.invalid_code);
  }, AUTH_MESSAGES.invalid_code);

  const resend = async () => {
    if (cooldown > 0 || pending) return;
    setError(null);
    setPending(true);
    try {
      // Omitting `code` makes both flows re-issue a fresh code rather than verify one.
      await signIn("password", {
        email,
        flow: mode === "reset" ? "reset" : "email-verification",
      });
      setInfo(`New code sent to ${email}.`);
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(friendlyAuthError(err, "We couldn't send a new code. Please try again."));
    } finally {
      setPending(false);
    }
  };

  const switchTo = (m: Mode) => {
    setError(null);
    setInfo(null);
    setCode("");
    setMode(m);
  };

  const shellProps = { pending, error, info };
  const strength = mode === "signUp" ? passwordProblems(password) : [];
  const resetStrength = mode === "reset" ? passwordProblems(newPassword) : [];

  const RememberMe = (
    <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
      <input
        type="checkbox"
        checked={remember}
        onChange={(e) => setRemember(e.target.checked)}
        className="h-4 w-4 rounded border-input accent-[hsl(var(--brand))]"
      />
      Keep me signed in
    </label>
  );

  const ResendButton = (
    <button
      type="button"
      onClick={resend}
      disabled={cooldown > 0 || pending}
      className="text-xs text-muted-foreground underline disabled:no-underline disabled:opacity-50"
    >
      {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
    </button>
  );

  return (
    <div className="flex flex-col items-center gap-3">
      {mode === "signIn" && (
        <>
          <Shell onSubmit={submitSignIn} cta="Sign in" {...shellProps}>
            <input className={input} aria-label="Email" type="email" autoComplete="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <input className={input} aria-label="Password" type="password" autoComplete="current-password" placeholder="Password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            {RememberMe}
          </Shell>
          <div className="flex w-72 justify-between">
            <Switch label="Create account" onClick={() => switchTo("signUp")} />
            <Switch label="Forgot password?" onClick={() => switchTo("forgot")} />
          </div>
        </>
      )}

      {mode === "signUp" && (
        <>
          <Shell onSubmit={submitSignUp} cta="Create account" {...shellProps}>
            <input className={input} aria-label="Email" type="email" autoComplete="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <input className={input} aria-label="Password" type="password" autoComplete="new-password" placeholder="Password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            {password.length > 0 && (
              <p className={`text-xs ${strength.length ? "text-text-secondary" : "text-success"}`}>
                {strength.length ? `Needs ${strength.join(", ")}.` : "Strong enough"}
              </p>
            )}
            {RememberMe}
          </Shell>
          <Switch label="Have an account? Sign in" onClick={() => switchTo("signIn")} />
        </>
      )}

      {mode === "verify" && (
        <>
          <Shell onSubmit={submitVerify} cta="Verify email" {...shellProps}>
            <p className="text-xs text-muted-foreground">Code sent to {email}</p>
            <input className={input} aria-label="Verification code" inputMode="numeric" autoComplete="one-time-code" placeholder="Verification code" required value={code} onChange={(e) => setCode(e.target.value)} />
          </Shell>
          <div className="flex w-72 justify-between">
            {ResendButton}
            <Switch label="Back to sign in" onClick={() => switchTo("signIn")} />
          </div>
        </>
      )}

      {mode === "forgot" && (
        <>
          <Shell onSubmit={submitForgot} cta="Send reset code" {...shellProps}>
            <input className={input} aria-label="Email" type="email" autoComplete="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Shell>
          <Switch label="Back to sign in" onClick={() => switchTo("signIn")} />
        </>
      )}

      {mode === "reset" && (
        <>
          <Shell onSubmit={submitReset} cta="Set new password" {...shellProps}>
            <p className="text-xs text-muted-foreground">Reset code for {email}</p>
            <input className={input} aria-label="Reset code" inputMode="numeric" autoComplete="one-time-code" placeholder="Reset code" required value={code} onChange={(e) => setCode(e.target.value)} />
            <input className={input} aria-label="New password" type="password" autoComplete="new-password" placeholder="New password" required value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            {newPassword.length > 0 && (
              <p className={`text-xs ${resetStrength.length ? "text-text-secondary" : "text-success"}`}>
                {resetStrength.length ? `Needs ${resetStrength.join(", ")}.` : "Strong enough"}
              </p>
            )}
          </Shell>
          <div className="flex w-72 justify-between">
            {ResendButton}
            <Switch label="Back to sign in" onClick={() => switchTo("signIn")} />
          </div>
        </>
      )}

      {googleEnabled && (
        <>
          <div className="flex w-72 items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>
          <Button
            variant="outline"
            className="w-72"
            onClick={() => {
              setRememberCookie(remember);
              void signIn("google", { redirectTo: redirectTo.current });
            }}
          >
            Continue with Google
          </Button>
        </>
      )}
    </div>
  );
}
