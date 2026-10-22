"use client";

import { Button } from "@v1/ui/button";
import { Input } from "@v1/ui/input";
import { CircleHelp, ExternalLink, Info } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { ApiError, describeError } from "@/lib/api/errors";
import { sendSupportRequest } from "@/lib/api/progress";
import {
  SUPPORT_KINDS,
  SUPPORT_MESSAGE_MAX,
  SUPPORT_MESSAGE_MIN,
  SUPPORT_SUBJECT_MAX,
  type SupportKind,
  type SupportRequestOut,
} from "@/lib/api/types";
import { legalLinks } from "@/lib/legal";
import { ChoiceGroup, Field, Notice, SectionHeading, SettingsCard } from "./primitives";
import { useUnsavedChanges } from "./use-unsaved-changes";

const KIND_LABELS: Record<SupportKind, string> = {
  question: "A question",
  bug: "Something isn't working",
  feedback: "Feedback or an idea",
  account: "My account",
};

const KIND_OPTIONS = SUPPORT_KINDS.map((kind) => ({ value: kind, label: KIND_LABELS[kind] }));

/** The short reference a student can quote in a reply: the start of the request's id. */
export function supportReference(request: Pick<SupportRequestOut, "id">): string {
  return request.id.replaceAll("-", "").slice(0, 8).toUpperCase();
}

function SupportForm() {
  const [kind, setKind] = useState<SupportKind>("question");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  // One id per request, kept across retries: resending after a network error returns the
  // request the API already has instead of making a second one.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState<SupportRequestOut | null>(null);
  useUnsavedChanges(!sent && Boolean(subject.trim() || message.trim()));

  const done = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sent) done.current?.focus(); // the form is gone: say what happened where focus was
  }, [sent]);

  const reason = (field: string) => (error instanceof ApiError ? error.reasonFor(field) : undefined);
  const tooShort = message.trim().length > 0 && message.trim().length < SUPPORT_MESSAGE_MIN;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || !subject.trim() || message.trim().length < SUPPORT_MESSAGE_MIN) return;
    setSending(true);
    setError(null);
    try {
      setSent(await sendSupportRequest({ requestId, kind, subject: subject.trim(), message: message.trim() }));
    } catch (failure) {
      setError(failure);
    } finally {
      setSending(false);
    }
  };

  const another = () => {
    setSent(null);
    setSubject("");
    setMessage("");
    setKind("question");
    setRequestId(crypto.randomUUID());
  };

  if (sent) {
    return (
      <div ref={done} tabIndex={-1} className="flex flex-col gap-3 outline-none">
        <Notice>
          <strong className="font-bold">We've received your request.</strong> Your reference is{" "}
          <strong className="font-mono font-bold">{supportReference(sent)}</strong>. Replies come by email, to the
          address on your account.
        </Notice>
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={another}>
          Send another
        </Button>
      </div>
    );
  }

  const failure = error ? describeError(error) : null;
  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <ChoiceGroup legend="What is it about?" value={kind} options={KIND_OPTIONS} onChange={setKind} />
      <Field
        label="Subject"
        hint={`Up to ${SUPPORT_SUBJECT_MAX} characters.`}
        error={reason("subject") ? "Check the subject." : null}
      >
        {(props) => (
          <Input
            {...props}
            className="w-full sm:max-w-[28rem]"
            value={subject}
            maxLength={SUPPORT_SUBJECT_MAX}
            required
            onChange={(event) => setSubject(event.target.value)}
          />
        )}
      </Field>
      <Field
        label="Message"
        hint={`${message.length.toLocaleString()} / ${SUPPORT_MESSAGE_MAX.toLocaleString()} characters. At least ${SUPPORT_MESSAGE_MIN}; up to 5 links.`}
        error={
          reason("message")
            ? `Check the message: at least ${SUPPORT_MESSAGE_MIN} characters and at most 5 links.`
            : tooShort
              ? `Write at least ${SUPPORT_MESSAGE_MIN} characters.`
              : null
        }
      >
        {(props) => (
          <textarea
            {...props}
            rows={6}
            value={message}
            maxLength={SUPPORT_MESSAGE_MAX}
            required
            onChange={(event) => setMessage(event.target.value)}
            className="focus-field w-full rounded-xl border border-input bg-card px-3 py-2 text-base sm:max-w-[28rem] sm:text-sm"
          />
        )}
      </Field>
      <p className="text-2xs text-text-secondary">
        Don't include passwords or sign-in codes. Your app version and browser are sent with it, to help us look into problems.
      </p>
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {failure.code === "validation_error" ? "Check the form and try again." : failure.message}
        </p>
      )}
      <Button type="submit" className="self-start" disabled={sending || !subject.trim() || message.trim().length < SUPPORT_MESSAGE_MIN}>
        {sending ? "Sending…" : "Send"}
      </Button>
    </form>
  );
}

export function HelpSection() {
  const legal = legalLinks();
  return (
    <>
      <SectionHeading title="Help & Support" description="Answers to common questions, and a way to reach us." />
      <div className="flex flex-col gap-4">
        <SettingsCard title="Get help">
          <ul className="flex flex-col gap-2 text-sm">
            <li>
              <Link href="/help" className="focus-ring inline-flex items-center gap-2 rounded font-semibold text-brand underline underline-offset-2">
                <CircleHelp aria-hidden className="h-4 w-4" />
                Help & FAQ
              </Link>
            </li>
            <li>
              <Link href="/about" className="focus-ring inline-flex items-center gap-2 rounded font-semibold text-brand underline underline-offset-2">
                <Info aria-hidden className="h-4 w-4" />
                About PadhAI
              </Link>
            </li>
            {legal.terms && (
              <li>
                <a
                  href={legal.terms}
                  target="_blank"
                  rel="noreferrer"
                  className="focus-ring inline-flex items-center gap-2 rounded font-semibold text-brand underline underline-offset-2"
                >
                  <ExternalLink aria-hidden className="h-4 w-4" />
                  Terms of Service<span className="sr-only"> (opens in a new tab)</span>
                </a>
              </li>
            )}
            {legal.privacy && (
              <li>
                <a
                  href={legal.privacy}
                  target="_blank"
                  rel="noreferrer"
                  className="focus-ring inline-flex items-center gap-2 rounded font-semibold text-brand underline underline-offset-2"
                >
                  <ExternalLink aria-hidden className="h-4 w-4" />
                  Privacy Policy<span className="sr-only"> (opens in a new tab)</span>
                </a>
              </li>
            )}
          </ul>
        </SettingsCard>
        <SettingsCard title="Contact support" description="Ask a question, report a problem or tell us what would help.">
          <SupportForm />
        </SettingsCard>
      </div>
    </>
  );
}
