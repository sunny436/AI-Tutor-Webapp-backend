/**
 * authEmail.ts — one factory for every code-bearing auth email.
 *
 * Replaces three near-identical `Email({...})` blocks (magic-link sign-in,
 * email verification, password reset) that previously lived in `ResendOTP.ts`
 * and `passwordProviders.ts`.
 *
 * Delivery is attempted in order — Resend → SMTP → log — by `email.sendAuthCode`.
 * The log fallback keeps local development working with no mail service at all.
 */
import { Email } from "@convex-dev/auth/providers/Email";
import { internal } from "./_generated/api";

/** How long a code stays valid. Kept in one place so the copy can quote it. */
export const CODE_TTL_SECONDS = 60 * 15;
export const CODE_TTL_MINUTES = CODE_TTL_SECONDS / 60;

type Ctx = { runAction: (ref: unknown, args: unknown) => Promise<unknown> };

/**
 * 8 digits from rejection-free sampling. `byte % 10` is biased (256 is not a
 * multiple of 10), which is fine for a short-lived, rate-limited OTP, but
 * discarding the biased tail costs nothing and keeps every digit uniform.
 */
function generateCode(): string {
  const digits: string[] = [];
  while (digits.length < 8) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    for (const b of bytes) {
      if (b < 250 && digits.length < 8) digits.push((b % 10).toString());
    }
  }
  return digits.join("");
}

/** Build one code-based email provider. */
export function authCodeProvider(config: {
  id: string;
  /** Used in the subject line and body, e.g. "sign-in". */
  purpose: string;
  subject: string;
  heading: string;
  intro: string;
}) {
  return Email({
    id: config.id,
    apiKey: process.env.RESEND_API_KEY,
    maxAge: CODE_TTL_SECONDS,
    generateVerificationToken: async () => generateCode(),
    sendVerificationRequest: async (
      { identifier, token }: { identifier: string; token: string },
      ctx?: Ctx,
    ) => {
      try {
        await ctx?.runAction(internal.email.sendAuthCode, {
          to: identifier,
          subject: config.subject,
          heading: config.heading,
          intro: config.intro,
          code: token,
          ttlMinutes: CODE_TTL_MINUTES,
        });
      } catch (error) {
        // Never let a mail failure take down the sign-in action itself — the code
        // is already stored, and the log fallback below keeps dev usable.
        console.error(
          `[auth] failed to send ${config.purpose} code to ${identifier}:`,
          (error as Error)?.message,
        );
        console.warn(`[auth] ${config.purpose} code for ${identifier}: ${token}`);
      }
    },
  });
}

/** Passwordless magic sign-in. */
export const ResendOTP = authCodeProvider({
  id: "resend-otp",
  purpose: "sign-in",
  subject: "Your Ayurveda sign-in code",
  heading: "Your sign-in code",
  intro: "Use this code to sign in to your Ayurveda account.",
});

/** Confirms an address after sign-up (and before a first password sign-in). */
export const ResendOTPVerify = authCodeProvider({
  id: "verify-otp",
  purpose: "email verification",
  subject: "Verify your Ayurveda email",
  heading: "Confirm your email",
  intro: "Enter this code to finish setting up your Ayurveda account.",
});

/** Password reset. */
export const ResendOTPReset = authCodeProvider({
  id: "password-reset",
  purpose: "password reset",
  subject: "Reset your Ayurveda password",
  heading: "Reset your password",
  intro:
    "Enter this code to choose a new password. If you didn't ask for this, you can ignore this email.",
});
