"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import { X } from "lucide-react";
import Link from "next/link";
import { createContext, useContext } from "react";

/** What the Settings workspace shares with its panel (settings-workspace.tsx). */
type Workspace = {
  closeHref: string;
  /** Open a section as if its link were used; `false` when the student chose to stay. */
  openSection: (slug: string) => boolean;
};

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <SettingsWorkspace>");
  return value;
}

export const iconButton =
  "focus-ring grid h-10 w-10 shrink-0 place-items-center rounded-xl text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground";

export function CloseSettings({ href, className }: { href: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link href={href} aria-label="Close settings" className={cn(iconButton, "border border-border", className)}>
          <X aria-hidden className="h-5 w-5" />
        </Link>
      </TooltipTrigger>
      <TooltipContent>Close settings</TooltipContent>
    </Tooltip>
  );
}
