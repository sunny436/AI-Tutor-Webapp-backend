import { Badge } from "@v1/ui/badge";
import { BookOpen, Languages, Leaf, ShieldCheck } from "lucide-react";
import { AuthForm } from "@/components/auth-form";
import { EmailOtpSignin } from "@/components/email-otp-signin";
import { ThemeSwitcher } from "@/components/theme-switcher";

export const metadata = {
  // Just the page name. The root layout's `title.template` appends "· Ayurveda",
  // so spelling the brand out here produced "Sign in · Ayurveda by Ollasoftware
  // · Ayurveda" in the browser tab.
  title: "Sign in",
};

/**
 * Sign in.
 *
 * WHAT THIS REPLACES
 *
 * The previous version was a checklist of the things the brief bans, all on one
 * screen: a 🌿 EMOJI as the brand mark in a gradient tile; a headline in
 * `bg-clip-text text-transparent` emerald→teal, the single most recognisable
 * "AI-generated page" tell; a blurred glowing blob positioned behind the card;
 * and `bg-white/70` glass over it. None of it used the design tokens — it was
 * hardcoded `emerald-*` throughout, so it did not even follow the palette the
 * rest of the app was tuned to.
 *
 * WHAT IT DOES INSTEAD
 *
 * Split screen. The left half is not decoration and not stock photography: it is
 * the product's actual claim, shown as the thing itself — a sourced answer with
 * its citation attached. That is what this app does that a chatbot does not, and
 * it is the most honest thing to put in front of someone deciding whether to
 * sign up. On mobile it collapses to a compact header, because a marketing panel
 * above the fold is a wall between the user and the form.
 *
 * Every function of the form is untouched: five modes, the OTP path, the Google
 * button's env gate, `?redirect=`, `rememberMe`, and all three `preflight*`
 * calls. The `w-72` / `w-64` widths inside it are load-bearing — `e2e/auth-live.js`
 * uses them to tell the password form from the magic-code one.
 */

const PROOF = [
  {
    icon: BookOpen,
    title: "Answers you can check",
    body: "Every plan is drawn from a curated Ayurveda knowledge base, and shows you which notes it came from.",
  },
  {
    icon: Languages,
    title: "English, Hindi or Hinglish",
    body: "Write however you speak. The reply comes back in the same language.",
  },
  {
    icon: ShieldCheck,
    title: "Careful by design",
    body: "Never names a medicine or a dose, and points you to a doctor when something needs one.",
  },
];

export default function Page() {
  return (
    <div className="relative min-h-dvh w-full bg-background lg:grid lg:grid-cols-[1.05fr_1fr]">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />

      {/* Left: what the product actually does. Hidden below lg. */}
      <section className="relative hidden flex-col justify-between border-r border-border bg-surface p-10 lg:flex xl:p-14">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-brand-foreground"
          >
            <Leaf className="h-[18px] w-[18px]" />
          </span>
          <span className="leading-tight">
            <span className="block font-display text-sm font-semibold text-foreground">
              Ayurveda
            </span>
            <span className="block text-2xs text-text-secondary">by Ollasoftware</span>
          </span>
        </div>

        <div className="max-w-md">
          {/* Deliberately NOT the landing page's headline. Both screens used
              "Ancient practice, answered carefully." and the two became hard to
              tell apart at a glance — reported as "this is the same page". The
              hero line belongs to `/`; this panel speaks to someone who has
              already decided and is signing in. */}
          <h2 className="font-display text-3xl font-semibold leading-tight tracking-tight text-foreground">
            Pick up where you left off.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Your consultations, the questions you answered, and the plans built from
            them — all saved to your account.
          </p>

          {/* A real answer with its citation, rendered the way the product
              renders it. Not a screenshot, not a mock-up of a chat window with
              invented content — the same Badge component the chat uses. */}
          <figure className="mt-7 rounded-xl border border-border bg-card p-4 elev-1">
            <figcaption className="sr-only">
              An example of how an answer shows its sources
            </figcaption>
            <p className="text-sm leading-relaxed text-text-secondary">
              <span className="font-medium text-foreground">Root cause.</span> Eating late
              and lying down soon after weakens digestion, so acid rises instead of
              settling.
            </p>
            <div className="mt-3 flex items-center gap-2 border-t border-border pt-2.5">
              <BookOpen aria-hidden className="h-3.5 w-3.5 shrink-0 text-accent-warm" />
              <span className="text-xs text-text-secondary">Based on</span>
              <Badge variant="source">acidity</Badge>
              <Badge variant="source">digestion</Badge>
            </div>
          </figure>

          <ul className="mt-8 space-y-4">
            {PROOF.map((item) => (
              <li key={item.title} className="flex gap-3">
                <span
                  aria-hidden
                  className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"
                >
                  <item.icon className="h-4 w-4" />
                </span>
                <span>
                  <span className="block text-sm font-medium text-foreground">
                    {item.title}
                  </span>
                  <span className="block text-xs leading-relaxed text-text-secondary">
                    {item.body}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-2xs text-text-secondary">
          Educational wellness guidance only. Not a diagnosis, and not a substitute for
          your doctor.
        </p>
      </section>

      {/* Right: the form. */}
      <section className="relative flex min-h-dvh flex-col items-center justify-center px-4 py-10 lg:min-h-0">
        <div className="absolute right-4 top-4">
          <ThemeSwitcher />
        </div>

        <div className="w-full max-w-sm">
          {/* Brand block, mobile only — the left panel carries it on desktop. */}
          <div className="mb-7 flex flex-col items-center text-center lg:hidden">
            <span
              aria-hidden
              className="grid h-11 w-11 place-items-center rounded-xl bg-brand text-brand-foreground"
            >
              <Leaf className="h-5 w-5" />
            </span>
            <span className="mt-3 font-display text-lg font-semibold text-foreground">
              Ayurveda
            </span>
            <span className="text-2xs text-text-secondary">by Ollasoftware</span>
          </div>

          <div className="mb-6 hidden lg:block">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
              Welcome back
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Sign in to pick up where you left off.
            </p>
          </div>
          <h1 className="sr-only lg:hidden">Sign in</h1>

          <div className="flex flex-col items-center gap-4">
            <AuthForm />

            <div className="flex w-72 max-w-full items-center gap-3 text-xs text-text-secondary">
              <span aria-hidden className="h-px flex-1 bg-border" />
              one-time email code
              <span aria-hidden className="h-px flex-1 bg-border" />
            </div>

            <EmailOtpSignin />
          </div>

          <p className="mt-8 text-center text-2xs text-text-secondary">
            © {new Date().getFullYear()} Ollasoftware · Ayurveda &amp; Yoga
          </p>
        </div>
      </section>
    </div>
  );
}
