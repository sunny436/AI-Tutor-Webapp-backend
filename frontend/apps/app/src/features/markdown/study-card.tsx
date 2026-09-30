import { cn } from "@v1/ui/utils";
import {
  BookOpen,
  CircleAlert,
  CircleCheck,
  Info,
  KeyRound,
  Lightbulb,
  ListOrdered,
  type LucideIcon,
  Sigma,
  TriangleAlert,
} from "lucide-react";
import { Children, type ReactElement, type ReactNode, isValidElement } from "react";

import type { HastNode } from "./hast";
import type { CardType } from "./remark-tutor";

const CARDS: Record<CardType, { label: string; icon: LucideIcon; tone: string }> = {
  note: { label: "Note", icon: Info, tone: "text-brand" },
  important: { label: "Important", icon: CircleAlert, tone: "text-destructive" },
  warning: { label: "Warning", icon: TriangleAlert, tone: "text-warning" },
  definition: { label: "Definition", icon: BookOpen, tone: "text-brand" },
  example: { label: "Example", icon: Lightbulb, tone: "text-brand" },
  steps: { label: "Step by step", icon: ListOrdered, tone: "text-brand" },
  answer: { label: "Answer", icon: CircleCheck, tone: "text-success" },
  takeaway: { label: "Key takeaway", icon: KeyRound, tone: "text-brand" },
  formula: { label: "Formula", icon: Sigma, tone: "text-brand" },
};

/**
 * The frame every study card shares (the reply's cards and the practice widgets alike): the
 * study-card background (the New Chat button's brand colour, 50 points lighter), the design
 * system's border, radius and spacing, and a header whose icon never carries meaning alone.
 */
export function CardFrame({
  icon: Icon,
  label,
  tone = "text-brand",
  title,
  kind,
  children,
  className,
}: {
  icon: LucideIcon;
  label: string;
  tone?: string;
  title?: ReactNode;
  kind: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-card={kind}
      className={cn(
        "study-card my-3 min-w-0 rounded-xl border border-border bg-study-card px-3.5 py-3 text-foreground sm:px-4",
        className,
      )}
    >
      <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm font-semibold leading-6">
        <Icon aria-hidden className={cn("h-4 w-4 shrink-0", tone)} />
        <span>{label}</span>
        {title ? (
          <>
            <span aria-hidden className="text-text-secondary">
              ·
            </span>
            <span className="min-w-0 break-words">{title}</span>
          </>
        ) : null}
      </div>
      <div className="study-card-body min-w-0">{children}</div>
    </div>
  );
}

/** A `:::type[Title]` card from a reply (remark-tutor.ts). The title, when given, is its first child. */
export function StudyCard({ type, children }: { type: CardType; children?: ReactNode }) {
  const card = CARDS[type] ?? CARDS.note;
  const items = Children.toArray(children);
  const at = items.findIndex(
    (item) => isValidElement(item) && Boolean((item.props as { node?: HastNode }).node?.properties?.dataCardTitle),
  );
  const title = at === -1 ? null : (items[at] as ReactElement<{ children?: ReactNode }>).props.children;
  const body = at === -1 ? items : items.filter((_, index) => index !== at);
  return (
    <CardFrame kind={type} icon={card.icon} label={card.label} tone={card.tone} title={title}>
      {body}
    </CardFrame>
  );
}
