"use client";

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@v1/ui/card";
import { Switch } from "@v1/ui/switch";
import { cn } from "@v1/ui/utils";
import { type ReactNode, useEffect, useId, useRef } from "react";

import { takeHeadingFocus } from "./heading-focus";

/**
 * The building blocks every Settings section uses, so they all look and behave alike: the
 * section's own heading (`h2`, the app header owns the `h1`), cards with an `h3`, labelled
 * fields whose hint and error are announced with the field, switches and choice groups.
 *
 * Product settings, not a form: on wide screens a field is a row (what it is | the control) and a
 * choice group sits beside its explanation; on phones everything stacks as before. The rows turn on
 * where the CARD is wide enough (the Settings sidebar takes 256-288px from md up): fields at lg,
 * pill groups at xl. Only layout changes: labels, hints, errors and fieldset names are wired to
 * their controls exactly as before, in the same DOM order.
 */

/**
 * The section's title. It is where focus goes when a section opens in place of what was used to
 * open it (a row of the phone list, search, arriving from the app): `data-settings-heading`
 * marks it for the workspace, and it takes focus itself if it mounts after the request (the
 * section was still loading). Not the page's first element, so Next's own focus call skips it.
 */
export function SectionHeading({ title, description }: { title: string; description: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (takeHeadingFocus()) heading.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="mb-6 md:mb-8">
      <h2
        ref={heading}
        tabIndex={-1}
        data-settings-heading=""
        className="font-display text-2xl font-bold tracking-tight text-foreground outline-none sm:text-[1.75rem]"
      >
        {title}
      </h2>
      <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-text-secondary">{description}</p>
    </div>
  );
}

export function SettingsCard({
  title,
  description,
  children,
  footer,
  tone = "default",
  titleAs = "h3",
}: {
  title: string;
  /** A card under a sub-heading of the section (the danger zone) steps down to h4. */
  titleAs?: "h3" | "h4";
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  tone?: "default" | "danger";
}) {
  return (
    <Card className={tone === "danger" ? "border-destructive/40" : undefined}>
      <CardHeader className="gap-1.5 p-6 md:p-7">
        <CardTitle as={titleAs}>{title}</CardTitle>
        {description && <CardDescription className="max-w-prose leading-relaxed">{description}</CardDescription>}
      </CardHeader>
      {children && <CardContent className="flex flex-col gap-6 px-6 pb-6 pt-0 md:px-7 md:pb-7">{children}</CardContent>}
      {footer && (
        <CardFooter
          className={cn(
            "justify-end gap-2 rounded-b-2xl",
            tone === "danger" ? "border-destructive/20 bg-destructive/5" : "bg-surface",
          )}
        >
          {footer}
        </CardFooter>
      )}
    </Card>
  );
}

/** A labelled control. `children` gets the ids that tie the label, hint and error to it. */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: true }) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  // Stacked: label, control, hint, error. From lg: label and hint on the left, the control and its
  // error on the right (grid placement only, so the DOM and reading order stay the same).
  return (
    <div className="flex flex-col gap-1.5 lg:grid lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start lg:gap-x-8 lg:gap-y-1">
      <label htmlFor={id} className="text-sm font-bold text-foreground lg:col-start-1 lg:row-start-1 lg:pt-2.5">
        {label}
      </label>
      <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1">
        {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      </div>
      {hint && (
        <p id={hintId} className="text-2xs text-text-secondary lg:col-start-1 lg:row-start-2">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-sm text-destructive lg:col-start-2 lg:row-start-3">
          {error}
        </p>
      )}
    </div>
  );
}

export function ToggleRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  label: string;
  description?: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-bold text-foreground">
          {label}
        </label>
        {description && (
          <p id={`${id}-description`} className="mt-0.5 text-sm text-text-secondary">
            {description}
          </p>
        )}
      </div>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-describedby={description ? `${id}-description` : undefined}
        className="mt-0.5"
      />
    </div>
  );
}

/** One choice from a few, as real radio buttons (arrow keys move between them). */
export function ChoiceGroup<T extends string>({
  legend,
  description,
  value,
  options,
  onChange,
}: {
  legend: string;
  description?: string;
  value: T;
  options: readonly { value: T; label: string; icon?: ReactNode }[];
  onChange: (value: T) => void;
}) {
  const name = useId();
  // A <fieldset> named by aria-labelledby rather than a <legend>, so the name can sit in a column
  // beside the pills: still a group with that name, of real radio buttons.
  return (
    <fieldset
      aria-labelledby={`${name}-legend`}
      aria-describedby={description ? `${name}-description` : undefined}
      className="xl:flex xl:items-start xl:justify-between xl:gap-8"
    >
      <div className="min-w-0 xl:max-w-[16rem] xl:flex-1 xl:pt-2">
        <p id={`${name}-legend`} className="text-sm font-bold text-foreground">
          {legend}
        </p>
        {description && (
          <p id={`${name}-description`} className="mt-0.5 text-sm text-text-secondary">
            {description}
          </p>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 xl:mt-0 xl:flex-[1.6] xl:justify-start">
        {options.map((option) => (
          <label key={option.value} className="relative">
            {/* The real radio lies over its pill, invisible: it is what a pointer, a keyboard and
                assistive technology all reach, and the pill below only shows its state. */}
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="peer absolute inset-0 z-10 cursor-pointer opacity-0"
            />
            <span
              className={cn(
                "flex min-h-10 cursor-pointer items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors",
                "border-border bg-card text-text-secondary hover:bg-surface-2 hover:text-foreground",
                "peer-checked:border-brand peer-checked:bg-brand-soft peer-checked:text-brand",
                "peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2",
              )}
            >
              {option.icon}
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** A calm notice inside a card: information, not an error. */
export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" }) {
  return (
    <div
      className={cn(
        "rounded-xl border px-3.5 py-3 text-sm leading-relaxed",
        tone === "warning"
          ? "border-accent-warm/30 bg-accent-warm-soft text-foreground"
          : "border-brand/20 bg-brand-soft text-foreground",
      )}
    >
      {children}
    </div>
  );
}
