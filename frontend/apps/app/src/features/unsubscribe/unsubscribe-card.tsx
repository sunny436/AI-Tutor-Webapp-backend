"use client";

import { Button } from "@v1/ui/button";
import Link from "next/link";
import { type ReactNode, type Ref, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/api/errors";
import { unsubscribe } from "@/lib/api/progress";
import { APP_NAME } from "@/lib/brand";
import { EMAIL_KINDS, isEmailKind, kindOfToken } from "./token";

type State = { step: "ask" } | { step: "sending" } | { step: "done"; label: string } | { step: "failed"; error: unknown };

/**
 * One button, never automatic: mail scanners open links, and opening this page must not
 * change anything. The API decides from the signed token; the kind read here only words it.
 */
export function UnsubscribeCard({ token }: { token: string | null }) {
  const kind = token ? kindOfToken(token) : null;
  const label = kind ? EMAIL_KINDS[kind] : "these emails";
  const [state, setState] = useState<State>({ step: "ask" });
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (state.step === "done" || state.step === "failed") heading.current?.focus();
  }, [state.step]);

  if (!token) {
    return (
      <Message title="This link is incomplete">
        Open the link again from the email. If it still doesn't work, you can change which emails you get in{" "}
        <SettingsLink />.
      </Message>
    );
  }

  const confirm = async () => {
    setState({ step: "sending" });
    try {
      const result = await unsubscribe(token);
      setState({ step: "done", label: isEmailKind(result.kind) ? EMAIL_KINDS[result.kind] : label });
    } catch (error) {
      setState({ step: "failed", error });
    }
  };

  if (state.step === "done") {
    return (
      <Message title="You're unsubscribed" headingRef={heading}>
        You won't get {state.label} from {APP_NAME} any more. You can turn them back on in <SettingsLink />.
      </Message>
    );
  }
  if (state.step === "failed") {
    const failure = describeError(state.error);
    return (
      <Message title={failure.title} headingRef={heading}>
        {failure.message} You can also change which emails you get in <SettingsLink />.
        {failure.action === "retry" || failure.action === "wait" ? (
          <Button type="button" variant="outline" className="mt-4 w-full" onClick={confirm}>
            Try again
          </Button>
        ) : null}
      </Message>
    );
  }
  return (
    <Message title={`Stop ${label}?`}>
      You'll stop getting {label} from {APP_NAME}. Other emails aren't affected.
      <Button type="button" className="mt-5 w-full" disabled={state.step === "sending"} onClick={confirm}>
        {state.step === "sending" ? "Unsubscribing…" : "Unsubscribe"}
      </Button>
    </Message>
  );
}

function SettingsLink() {
  return (
    <Link href="/settings/notifications" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
      Settings › Notifications
    </Link>
  );
}

function Message({
  title,
  headingRef,
  children,
}: {
  title: string;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col">
      <h1 ref={headingRef} tabIndex={-1} className="font-display text-xl font-bold tracking-tight text-foreground outline-none">
        {title}
      </h1>
      <div className="mt-2 text-sm leading-relaxed text-text-secondary">{children}</div>
    </div>
  );
}
