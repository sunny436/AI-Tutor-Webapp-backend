import { Badge } from "@v1/ui/badge";
import { Button } from "@v1/ui/button";
import {
  ArrowRight,
  BookOpen,
  FileText,
  Languages,
  Leaf,
  MessageSquare,
  Mic,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { ThemeSwitcher } from "@/components/theme-switcher";

/**
 * The public landing page.
 *
 * EVERY CLAIM ON THIS PAGE IS BACKED BY CODE THAT EXISTS.
 *
 * The reference site this was briefed against leads on "every recommendation
 * verified and traced back to authentic Ayurvedic texts" and shows no evidence
 * for it. This product can actually do that — `retrieval/pipeline.py` returns
 * the filename and relevance of every passage used — so the page is built around
 * demonstrating it rather than asserting it.
 *
 * DELIBERATELY ABSENT, because the features do not exist:
 *   - no Prakriti/dosha quiz          (no scoring code, no schema, anywhere)
 *   - no assessments                  (zero matches in the codebase)
 *   - no herb / formulation / recipe library
 *   - no pricing                      (billing is the template's generic
 *                                      Free/PRO and nothing checks a
 *                                      subscription — advertising it would be
 *                                      inventing a product)
 *   - no testimonials, no user counts, no "trusted by" logos, no statistics
 *
 * The only numbers on this page are 29 (files in `data/knowledge/`) and 3
 * (languages `detect_language` actually returns). Both are countable.
 */

const HOW = [
  {
    step: "01",
    title: "Say what's wrong",
    body: "One line, in English, Hindi or Hinglish. No forms to fill in first.",
  },
  {
    step: "02",
    title: "Tap through a few questions",
    body: "Written for your specific problem, not a fixed questionnaire — acidity and hair fall get different questions.",
  },
  {
    step: "03",
    title: "Read the plan",
    body: "Root cause, what to change, food chart, yoga and breathing, daily routine — and when to see a doctor.",
  },
  {
    step: "04",
    title: "Check where it came from",
    body: "Every answer shows which notes it was drawn from, so you can see the reasoning rather than trust it.",
  },
];

const FEATURES = [
  {
    icon: MessageSquare,
    title: "Questions written for you",
    body: "The assistant decides what it needs to know from what you describe. Nothing is hardcoded per condition.",
  },
  {
    icon: BookOpen,
    title: "Grounded in real notes",
    body: "Answers are retrieved from a curated Ayurveda knowledge base, not recalled from a language model's memory.",
  },
  {
    icon: Languages,
    title: "Your language",
    body: "English, Hindi and Hinglish. Write however you speak; the reply comes back the same way.",
  },
  {
    icon: Mic,
    title: "Speak or type",
    body: "Dictate your problem if typing is awkward. What you said goes into the box first, so you can correct it.",
  },
  {
    icon: FileText,
    title: "Bring your reports",
    body: "Attach a PDF or a photo of a lab report inside a consultation and ask questions about it.",
  },
  {
    icon: ShieldCheck,
    title: "Careful about limits",
    body: "Never names a medicine or a dose. Recognises what needs a doctor and says so instead of guessing.",
  },
];

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-brand-foreground"
          >
            <Leaf className="h-4 w-4" />
          </span>
          <span className="font-display text-base font-semibold text-foreground">
            Ayurveda
          </span>
        </Link>

        <nav aria-label="Main" className="ml-auto hidden items-center gap-6 md:flex">
          <a
            href="#how"
            className="text-sm text-text-secondary transition-colors hover:text-foreground"
          >
            How it works
          </a>
          <a
            href="#features"
            className="text-sm text-text-secondary transition-colors hover:text-foreground"
          >
            Features
          </a>
          <a
            href="#sources"
            className="text-sm text-text-secondary transition-colors hover:text-foreground"
          >
            Sources
          </a>
        </nav>

        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <div className="hidden sm:block">
            <ThemeSwitcher />
          </div>
          <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/login">Get started</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}

export function Landing() {
  return (
    <div className="relative min-h-dvh bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="relative">
        <Nav />

        {/* HERO */}
        <section className="mx-auto w-full max-w-6xl px-4 pb-16 pt-14 sm:px-6 sm:pb-24 sm:pt-20">
          <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_1fr]">
            <div>
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-secondary">
                <Sparkles aria-hidden className="h-3.5 w-3.5 text-accent-warm" />
                Ayurveda &amp; Yoga, answered from sources
              </span>

              <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.08] tracking-tight text-foreground sm:text-5xl">
                Ancient practice,
                <br />
                answered carefully.
              </h1>

              <p className="mt-5 max-w-xl text-base leading-relaxed text-text-secondary">
                Describe what&apos;s troubling you in one line. Tap through a few
                questions written for your problem. Get a plan — root cause, food chart,
                yoga, daily routine — drawn from a curated Ayurveda knowledge base, with
                the notes it came from shown alongside it.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <Button asChild size="lg">
                  <Link href="/login">
                    Start a consultation
                    <ArrowRight aria-hidden className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <a href="#how">See how it works</a>
                </Button>
              </div>

              <p className="mt-4 text-xs text-text-secondary">
                Free while in development. Educational wellness guidance — not a
                diagnosis, and not a replacement for your doctor.
              </p>
            </div>

            {/* The product, not a stock photo. This is the real chat surface:
                the same Badge component, the same section styling, the same
                provenance row that a real answer renders. */}
            <div className="rounded-2xl border border-border bg-card p-4 elev-3 sm:p-5">
              <div className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground">
                  Mujhe raat ko acidity ho jaati hai
                </p>
              </div>

              <div className="mt-4 flex gap-3">
                <span
                  aria-hidden
                  className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground"
                >
                  <Leaf className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-border bg-surface p-3.5">
                  <div className="rounded-xl border border-accent-warm/25 bg-accent-warm-soft/50 p-3">
                    <p className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-accent-warm">
                      <span
                        aria-hidden
                        className="grid h-5 w-5 place-items-center rounded-md bg-accent-warm/15"
                      >
                        <BookOpen className="h-3 w-3" />
                      </span>
                      Root Cause
                    </p>
                    <p className="text-sm leading-relaxed text-text-secondary">
                      Late dinner and lying down soon after weakens digestion, so acid
                      rises instead of settling.
                    </p>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
                    <BookOpen
                      aria-hidden
                      className="h-3.5 w-3.5 shrink-0 text-accent-warm"
                    />
                    <span className="text-xs text-text-secondary">Based on</span>
                    <Badge variant="source">acidity</Badge>
                    <Badge variant="source">digestion</Badge>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* SOURCES — the differentiator, given its own section */}
        <section
          id="sources"
          className="scroll-mt-20 border-y border-border bg-surface py-16 sm:py-20"
        >
          <div className="mx-auto grid w-full max-w-6xl items-center gap-10 px-4 sm:px-6 lg:grid-cols-2">
            <div>
              <p className="font-mono text-xs uppercase tracking-widest text-accent-warm">
                Why it can be checked
              </p>
              <h2 className="mt-3 font-display text-3xl font-semibold tracking-tight text-foreground">
                It looks the answer up.
              </h2>
              <p className="mt-4 leading-relaxed text-text-secondary">
                Most AI health tools generate an answer from what a language model
                absorbed during training — fluent, confident, and impossible to verify.
                This one searches a knowledge base of{" "}
                <strong className="font-semibold text-foreground">
                  29 curated Ayurveda notes
                </strong>{" "}
                first, writes from what it found, and then tells you which notes those
                were.
              </p>
              <p className="mt-3 leading-relaxed text-text-secondary">
                If nothing relevant is found, it says so instead of inventing a remedy.
              </p>
            </div>

            <ol className="space-y-3">
              {[
                "Your message",
                "Questions chosen for your problem",
                "Search the Ayurveda notes",
                "Write the plan from what was found",
                "Show the sources",
              ].map((label, index) => (
                <li key={label} className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-soft font-mono text-xs text-brand"
                  >
                    {index + 1}
                  </span>
                  <span className="text-sm text-foreground">{label}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-6 sm:py-20">
          <h2 className="font-display text-3xl font-semibold tracking-tight text-foreground">
            How it works
          </h2>
          <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {HOW.map((item) => (
              <div key={item.step}>
                {/* Numbered because this genuinely is a sequence — each step
                    depends on the one before it. */}
                <p className="font-mono text-xs text-accent-warm">{item.step}</p>
                <h3 className="mt-2 font-display text-base font-semibold text-foreground">
                  {item.title}
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* FEATURES */}
        <section
          id="features"
          className="scroll-mt-20 border-t border-border bg-surface py-16 sm:py-20"
        >
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <h2 className="font-display text-3xl font-semibold tracking-tight text-foreground">
              What it does
            </h2>
            <div className="mt-8 grid gap-x-8 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature) => (
                <div key={feature.title} className="flex gap-3.5">
                  <span
                    aria-hidden
                    className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"
                  >
                    <feature.icon className="h-[18px] w-[18px]" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="font-display text-base font-semibold text-foreground">
                      {feature.title}
                    </h3>
                    <p className="mt-1 text-sm leading-relaxed text-text-secondary">
                      {feature.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* SAFETY — on a health product this belongs above the fold of the
            decision, not buried in a footer disclaimer */}
        <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
          <div className="rounded-2xl border border-border bg-card p-6 sm:p-8">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
              <span
                aria-hidden
                className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"
              >
                <ShieldCheck className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2 className="font-display text-xl font-semibold text-foreground">
                  What it will not do
                </h2>
                <ul className="mt-3 grid gap-2 text-sm leading-relaxed text-text-secondary sm:grid-cols-2">
                  <li>Name a medicine, brand or dosage — ever.</li>
                  <li>Diagnose you, or replace your doctor.</li>
                  <li>Guess when the notes have no answer.</li>
                  <li>Stay quiet about symptoms that need urgent care.</li>
                </ul>
                <p className="mt-4 text-sm leading-relaxed text-text-secondary">
                  Every plan ends with when to see a doctor, and that section is not
                  optional — it is added to every answer by the system, not by the model.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto w-full max-w-6xl px-4 pb-20 sm:px-6">
          <div className="rounded-2xl border border-brand/20 bg-brand-soft/50 px-6 py-12 text-center sm:px-10">
            <h2 className="font-display text-3xl font-semibold tracking-tight text-foreground">
              Tell it what&apos;s troubling you.
            </h2>
            <p className="mx-auto mt-3 max-w-md leading-relaxed text-text-secondary">
              One line is enough. It takes about a minute to get a plan you can act on.
            </p>
            <Button asChild size="lg" className="mt-7">
              <Link href="/login">
                Start a consultation
                <ArrowRight aria-hidden className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>

        {/* FOOTER — only links that exist */}
        <footer className="border-t border-border">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden
                className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-brand-foreground"
              >
                <Leaf className="h-4 w-4" />
              </span>
              <span className="leading-tight">
                <span className="block font-display text-sm font-semibold text-foreground">
                  Ayurveda
                </span>
                <span className="block text-2xs text-text-secondary">
                  by Ollasoftware
                </span>
              </span>
            </div>

            <nav aria-label="Footer" className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <a
                href="#how"
                className="text-sm text-text-secondary transition-colors hover:text-foreground"
              >
                How it works
              </a>
              <a
                href="#features"
                className="text-sm text-text-secondary transition-colors hover:text-foreground"
              >
                Features
              </a>
              <Link
                href="/login"
                className="text-sm text-text-secondary transition-colors hover:text-foreground"
              >
                Sign in
              </Link>
            </nav>
          </div>
          <div className="mx-auto w-full max-w-6xl px-4 pb-10 sm:px-6">
            <p className="text-2xs leading-relaxed text-text-secondary">
              © {new Date().getFullYear()} Ollasoftware. Educational wellness guidance
              based on Ayurveda and Yoga. Not medical advice, not a diagnosis, and not a
              substitute for consulting a qualified practitioner. If you have urgent
              symptoms, contact a doctor or emergency services.
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
