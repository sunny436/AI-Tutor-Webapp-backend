import { ChevronDown } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { APP_NAME } from "@/lib/brand";

/**
 * /help and /about. Plain server-rendered pages, written to be true of the app as it is
 * today: when a feature changes, change its answer here in the same commit.
 */

function inline(href: string, text: string) {
  return (
    <Link href={href} className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
      {text}
    </Link>
  );
}

export function PageFrame({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <div className="h-full overflow-y-auto">
      <article className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 md:py-8">
        <header>
          <h2 className="font-display text-2xl font-bold tracking-tight text-foreground">{title}</h2>
          <p className="mt-1 max-w-prose text-sm leading-relaxed text-text-secondary">{intro}</p>
        </header>
        {children}
      </article>
    </div>
  );
}

type Faq = { question: string; answer: ReactNode };

const FAQ: readonly { topic: string; items: readonly Faq[] }[] = [
  {
    topic: "Using the tutor",
    items: [
      {
        question: `What can I ask ${APP_NAME}?`,
        answer: (
          <>
            Any question from your studies: a doubt from class, a step you didn't follow, a topic to revise. Ask in
            your own words, and ask follow-up questions in the same chat.
          </>
        ),
      },
      {
        question: "Can the tutor be wrong?",
        answer: (
          <>
            Yes. It's an AI and it can make mistakes, including confident-sounding ones. Check anything important
            against your textbook or ask your teacher.
          </>
        ),
      },
      {
        question: "How do I make the tutor fit how I learn?",
        answer: (
          <>
            Fill in {inline("/settings/academic", "Academic Profile")}, {inline("/settings/learning", "Learning Preferences")}{" "}
            and {inline("/settings/tutor", "AI Tutor")}. The AI Tutor page shows exactly what your tutor is told. Your
            name, email address and photo are never sent to it.
          </>
        ),
      },
      {
        question: "How do I stop a reply?",
        answer: <>Press Stop while it's writing. Leaving the page or closing the tab stops it too.</>,
      },
      {
        question: "Can the tutor read my files?",
        answer: (
          <>
            Yes. Attach a PDF, Word, PowerPoint, Excel, CSV, text file or a photo of printed text with the paperclip, or
            add it in the {inline("/library", "File Library")}. You can send once a file shows Ready. The tutor then uses
            the files attached in that chat; from a large file it reads the parts that fit your question. You have 100 MB
            of storage; deleting a file frees its space. Handwriting, maths written by hand, diagrams and charts are not
            read. To find what a file says, its text is sent to our AI provider, like your messages.
          </>
        ),
      },
      {
        question: "How does dictation work?",
        answer: (
          <>
            Press the microphone, speak, and your words appear in the message box; nothing is sent until you press Send.
            Speech is turned into text by your browser (Chrome and Edge use Google's service, Safari uses Apple's);{" "}
            {APP_NAME} never receives or stores your voice. Firefox does not support dictation, so the microphone isn't
            shown there.
          </>
        ),
      },
    ],
  },
  {
    topic: "Progress",
    items: [
      {
        question: "How is active time measured?",
        answer: (
          <>
            A minute counts when {APP_NAME} is open and on screen, and within the last two minutes you used it (typed,
            clicked, scrolled) or a reply was being written. At most one minute counts per minute, however many tabs or
            devices you use. It measures time in the app, not all of your studying.
          </>
        ),
      },
      {
        question: "What is a streak?",
        answer: (
          <>
            The number of days in a row on which you were active for at least a minute or asked a question. Days follow
            the time zone in your {inline("/settings/profile", "Profile")}. See yours in{" "}
            {inline("/settings/progress", "Progress & Goals")}.
          </>
        ),
      },
    ],
  },
  {
    topic: "Emails",
    items: [
      {
        question: "Will you send me emails?",
        answer: (
          <>
            Study reminders and summaries are off until you turn them on in{" "}
            {inline("/settings/notifications", "Notifications")}, and every one has a link to stop it. Security emails
            are on: when your password changes and, unless you turn it off, when your account is signed in on a new
            device. The Notifications page says if sending emails is paused.
          </>
        ),
      },
    ],
  },
  {
    topic: "Your account",
    items: [
      {
        question: "How do I change my email address?",
        answer: (
          <>
            In {inline("/settings/profile", "Profile")}. You'll need your password, and a code we send to the new
            address.
          </>
        ),
      },
      {
        question: "I think someone else is using my account.",
        answer: (
          <>
            In {inline("/settings/privacy", "Privacy & Security")}, change your password, then sign out every other
            device. You'll see there which devices are signed in.
          </>
        ),
      },
      {
        question: "How do I delete my account?",
        answer: (
          <>
            In {inline("/settings/privacy", "Privacy & Security")}. It deletes your account, chats, settings and
            progress straight away, and it can't be undone. Copies in our backups are removed when those backups expire.
          </>
        ),
      },
    ],
  },
];

export function HelpPage() {
  return (
    <PageFrame title="Help & FAQ" intro={`Answers to common questions about ${APP_NAME}.`}>
      {FAQ.map((group, index) => (
        <section key={group.topic} aria-labelledby={`faq-${index}`} className="flex flex-col gap-2">
          <h3 id={`faq-${index}`} className="text-sm font-bold uppercase tracking-wide text-text-secondary">
            {group.topic}
          </h3>
          <div className="divide-y divide-border rounded-2xl border border-border bg-card">
            {group.items.map((item) => (
              <details key={item.question} className="group">
                <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-4 py-3.5 text-sm font-semibold text-foreground [&::-webkit-details-marker]:hidden">
                  {item.question}
                  <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-text-secondary transition-transform group-open:rotate-180" />
                </summary>
                <p className="px-4 pb-4 text-sm leading-relaxed text-text-secondary">{item.answer}</p>
              </details>
            ))}
          </div>
        </section>
      ))}
      <p className="text-sm text-text-secondary">
        Didn't find your answer? {inline("/settings/help", "Contact support")}.
      </p>
    </PageFrame>
  );
}

export function AboutPage() {
  return (
    <PageFrame title={`About ${APP_NAME}`} intro="What it is, and how it treats your data.">
      <section className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5 text-sm leading-relaxed text-foreground">
        <h3 className="font-bold">What it does</h3>
        <p>
          {APP_NAME} is an AI tutor for school students. You ask questions in a chat and it explains, step by step when
          you want, in the language and at the depth you choose. It can draw on study material we've added, and it
          adapts to the class, board and subjects you tell it about.
        </p>
        <p>It's a study aid, not a replacement for your teachers or textbooks, and it can make mistakes.</p>
      </section>
      <section className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5 text-sm leading-relaxed text-foreground">
        <h3 className="font-bold">Your data</h3>
        <ul className="list-disc space-y-1.5 pl-5">
          <li>Your chats, settings and progress are stored with your account. Other users can't see them.</li>
          <li>The tutor is told your learning settings, never your name, email address or photo.</li>
          <li>Active time comes only from how you use the app, and it's never compared with anyone else's.</li>
          <li>
            You can delete your account, and everything with it, at any time in{" "}
            {inline("/settings/privacy", "Privacy & Security")}.
          </li>
        </ul>
      </section>
      <p className="text-sm text-text-secondary">
        Questions? See {inline("/help", "Help & FAQ")} or {inline("/settings/help", "contact support")}.
      </p>
    </PageFrame>
  );
}
