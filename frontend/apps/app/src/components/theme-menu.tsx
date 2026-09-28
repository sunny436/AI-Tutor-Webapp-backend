"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@v1/ui/dropdown-menu";

import { THEME_CHOICES, ThemeIcon, useThemeChoice } from "./theme-switcher";

const LABELS: Record<(typeof THEME_CHOICES)[number], string> = { light: "Light", dark: "Dark", system: "System" };

/**
 * The app header's theme control: the current choice's icon, opening Light / Dark / System with a
 * check on the one in use. The same choice and icons as ThemeSwitcher (theme-switcher.tsx), in a
 * compact popover. Not modal, like the bell: the page stays in the accessibility tree.
 */
export function ThemeMenu() {
  const { shown, choose } = useThemeChoice();
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Colour theme"
          title="Colour theme"
          className="focus-ring grid h-9 w-9 shrink-0 place-items-center rounded-full border border-border bg-card text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground data-[state=open]:bg-surface-2 data-[state=open]:text-foreground"
        >
          {/* No icon until mounted: the server can't know the theme, and a wrong one would flash. */}
          {shown ? <ThemeIcon theme={shown} className="h-4 w-4" /> : <span className="h-4 w-4" />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={6} collisionPadding={8} className="min-w-[9.5rem] p-1">
        <DropdownMenuRadioGroup value={shown} onValueChange={choose}>
          {THEME_CHOICES.map((theme) => (
            <DropdownMenuRadioItem key={theme} value={theme} className="gap-2.5 font-medium">
              <ThemeIcon theme={theme} className="h-4 w-4 text-text-secondary" />
              {LABELS[theme]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
