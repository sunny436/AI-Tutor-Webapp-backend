"use client";

import { AUTH_MESSAGES, friendlyAuthError } from "@/lib/auth-errors";
import { useAuthActions } from "@convex-dev/auth/react";
import { Button } from "@v1/ui/button";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const inputCls =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-base outline-none transition-colors placeholder:text-text-secondary focus:border-brand/60 focus:ring-2 focus:ring-brand/20 sm:h-10 sm:text-sm";

const RESEND_COOLDOWN_SECONDS = 30;

function safeRedirect(target: string | null): string {
  if (!target || !target.startsWith("/") || target.startsWith("//")) return "/";
  return target;
}

export function EmailOtpSignin() {
  const router = useRouter();
  const { signIn } = useAuthActions();
  const [step, setStep] = useState<"signIn" | { email: string }>("signIn");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const sendCode = async (email: string) => {
    setError(null);
    setPending(true);
    try {
      await signIn("resend-otp", { email });
      setStep({ email });
      setInfo(`Code sent to ${email}.`);
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(friendlyAuthError(err, "We couldn't send a code. Please try again."));
    } finally {
      setPending(false);
    }
  };

  if (step === "signIn") {
    return (
      <form
        className="flex w-64 flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          const email = String(new FormData(e.currentTarget).get("email") ?? "");
          void sendCode(email);
        }}
      >
        <input
          name="email"
          type="email"
          autoComplete="email"
          required
          placeholder="you@example.com"
          // A placeholder is not a label: it disappears the moment you type, so
          // this field announced as an unnamed textbox once focused. It also
          // needs to say WHICH email form this is — there are two on the page.
          aria-label="Email for a one-time code"
          className={inputCls}
        />
        <Button type="submit" variant="outline" className="w-full" disabled={pending}>
          {pending ? "Sending…" : "Send code"}
        </Button>
        {error && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {error}
          </p>
        )}
      </form>
    );
  }

  return (
    <form
      className="flex w-64 flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        const code = String(new FormData(e.currentTarget).get("code") ?? "").trim();
        setPending(true);
        void signIn("resend-otp", { email: step.email, code })
          .then((result) => {
            // A rejected code can surface either as a throw or as `signingIn: false`,
            // depending on where it failed — treat both as an invalid code rather
            // than leaving the form silently doing nothing.
            if (result?.signingIn) {
              router.replace(
                safeRedirect(new URLSearchParams(window.location.search).get("redirect")),
              );
              router.refresh();
              return;
            }
            setError(AUTH_MESSAGES.invalid_code);
          })
          .catch((err) => setError(friendlyAuthError(err, AUTH_MESSAGES.invalid_code)))
          .finally(() => setPending(false));
      }}
    >
      <p className="text-xs text-muted-foreground">
        Code sent to <span className="font-mono">{step.email}</span>
      </p>
      <input
        name="code"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        placeholder="8-digit code"
        aria-label="8-digit code"
        className={inputCls}
      />
      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Verifying…" : "Continue"}
      </Button>
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => void sendCode(step.email)}
          disabled={cooldown > 0 || pending}
          className="text-xs text-text-secondary underline underline-offset-2 transition-colors hover:text-foreground disabled:no-underline disabled:opacity-50"
        >
          {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
        </button>
        <button
          type="button"
          className="text-xs text-text-secondary underline underline-offset-2 transition-colors hover:text-foreground"
          onClick={() => {
            setStep("signIn");
            setError(null);
            setInfo(null);
          }}
        >
          Use a different email
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
      {info && !error && <p className="text-xs text-muted-foreground">{info}</p>}
    </form>
  );
}
