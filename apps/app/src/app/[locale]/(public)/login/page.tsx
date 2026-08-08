import { AuthForm } from "@/components/auth-form";
import { EmailOtpSignin } from "@/components/email-otp-signin";

export const metadata = {
  title: "Sign in · Ayurveda by Ollasoftware",
};

export default function Page() {
  return (
    <div className="relative flex h-screen w-screen flex-col items-center justify-center bg-gradient-to-br from-emerald-50 via-white to-teal-50 px-4 dark:from-zinc-950 dark:via-black dark:to-emerald-950/40">
      {/* soft glow */}
      <div className="pointer-events-none absolute left-1/2 top-24 h-72 w-72 -translate-x-1/2 rounded-full bg-emerald-400/20 blur-3xl" />

      <div className="relative z-10 w-full max-w-sm rounded-3xl border border-emerald-500/15 bg-white/70 p-8 shadow-xl backdrop-blur dark:bg-white/[0.04]">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-3xl shadow-lg shadow-emerald-500/30">
            🌿
          </span>
          <h1 className="mt-4 bg-gradient-to-r from-emerald-600 to-teal-600 bg-clip-text text-2xl font-bold text-transparent dark:from-emerald-400 dark:to-teal-300">
            Ayurveda
          </h1>
          <p className="text-xs font-medium tracking-wide text-primary/40">by Ollasoftware</p>
          <p className="mt-2 text-sm text-primary/60">Sign in to your wellness dashboard</p>
        </div>

        <div className="flex flex-col items-center gap-4">
          <AuthForm />
          <div className="flex w-72 items-center gap-3 text-xs text-primary/40">
            <span className="h-px flex-1 bg-border" />
            one-time email code
            <span className="h-px flex-1 bg-border" />
          </div>
          <EmailOtpSignin />
        </div>
      </div>

      <p className="relative z-10 mt-6 text-xs text-primary/40">
        © {new Date().getFullYear()} Ollasoftware · Ayurveda &amp; Yoga
      </p>
    </div>
  );
}
