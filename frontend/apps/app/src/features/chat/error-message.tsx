"use client";

import { Button } from "@v1/ui/button";
import { AlertTriangle } from "lucide-react";

import { type ErrorCode, describeCode } from "@/lib/api/errors";

/**
 * A failure, shown as a failure — not dressed up as something the assistant said.
 * Our own copy per error code, one recovery action, and the request id for the
 * cases worth reporting.
 */
export function ErrorMessage({
  code,
  requestId,
  onRetry,
  retryLabel = "Try again",
}: {
  code: ErrorCode;
  requestId?: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  const description = describeCode(code, requestId);
  return (
    <div
      role="alert"
      className="mt-2 flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
    >
      <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{description.title}</p>
        <p className="mt-0.5 leading-relaxed">{description.message}</p>
        {description.code === "internal_error" && requestId && (
          <p className="mt-1 font-mono text-2xs opacity-80">Reference: {requestId}</p>
        )}
        {description.action === "sign_in" ? (
          <Button asChild size="sm" variant="destructive" className="mt-2">
            <a href="/login">Sign in again</a>
          </Button>
        ) : description.action === "retry" && onRetry ? (
          <Button type="button" size="sm" variant="outline" className="mt-2" onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
