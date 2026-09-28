"use client";

import { Select, SelectContent, SelectItem, SelectTrigger } from "@v1/ui/select";
import { cn } from "@v1/ui/utils";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import type { Theme } from "@/lib/api/types";
import { useAppearance } from "./appearance-provider";

/**
 * The theme control.
 *
 * MOVED HERE from `(dashboard)/_components/`, because that is inside the
 * authenticated route group and the component was mounted in exactly one place:
 * the sidebar footer. So the theme could only be changed from a signed-in
 * dashboard page — not on login, onboarding, the 404, or the error boundary.
 *
 * That is not a small gap. Someone who prefers dark mode meets this product on
 * the login screen, which is the one page that could not honour the preference
 * they had just been unable to set. And the error page is where a light flash at
 * 2am is least welcome.
 *
 * `next-themes` handles the value itself; this is only the control, so mounting
 * it on public pages costs nothing and changes no behaviour. The app header's
 * compact menu (theme-menu.tsx) shares the same choice and icons below.
 */

export const THEME_CHOICES = ["light", "dark", "system"] as const;

/**
 * The one theme choice both controls use: next-themes' value (only once mounted, since the theme
 * is unknown on the server), and a change that also saves it to the account when signed in.
 */
export function useThemeChoice() {
  const { theme: currentTheme, setTheme, themes } = useTheme();
  // Signed in, the choice is saved to the account (every device); elsewhere only this browser.
  const appearance = useAppearance();
  // Avoid hydration mismatch: the theme is unknown on the server, so only show
  // the theme-dependent icon/label after the component has mounted on the client.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const shown = mounted ? currentTheme : undefined;
  const choose = (theme: string) => {
    setTheme(theme);
    appearance?.change({ theme: theme as Theme });
  };
  return { shown, themes, choose };
}

/** The icon of a theme choice (System, or not known yet: the monitor). */
export function ThemeIcon({ theme, className }: { theme: string | undefined; className?: string }) {
  if (theme === "light") return <Sun aria-hidden className={className} />;
  if (theme === "dark") return <Moon aria-hidden className={className} />;
  return <Monitor aria-hidden className={className} />;
}

export function ThemeSwitcher({ triggerClass, showLabel = true }: { triggerClass?: string; showLabel?: boolean }) {
  const { shown, themes, choose } = useThemeChoice();

  return (
    <Select
      // `shown`, not `currentTheme`. The icon and label were already guarded but
      // this prop was not, and it is the one that actually broke hydration:
      // Radix stamps `data-placeholder` on the trigger whenever the value is
      // empty, so the server (theme unknown -> placeholder) and the client
      // (theme known -> no placeholder) disagreed on the DOM attributes and
      // React threw "Hydration failed because the initial UI does not match".
      // Feeding it the same mount-guarded value keeps both renders identical.
      value={shown}
      onValueChange={choose}
    >
      <SelectTrigger
        // The trigger has no visible label, so without this it announces as an
        // unnamed combobox.
        aria-label="Colour theme"
        title={showLabel ? undefined : "Colour theme"}
        // `size="sm"` rather than a `h-7 … !px-2` className override: see the
        // note on selectTriggerVariants in packages/ui/src/components/select.tsx
        // for why an override here is a breakpoint hazard.
        size="sm"
        // `w-auto`: the trigger is `w-full` by default, which stretched this
        // control across the sign-in header. `!flex`: the trigger clamps its
        // first span to one line with a vertical box, which stacked the icon
        // above the label.
        className={cn("w-auto shrink-0 border-border bg-surface-2", triggerClass)}
      >
        <span className="!flex items-center gap-2 whitespace-nowrap">
          <ThemeIcon theme={shown} className="h-[14px] w-[14px]" />
          {shown && showLabel && (
            <span className="text-xs font-medium">
              {shown.charAt(0).toUpperCase() + shown.slice(1)}
            </span>
          )}
        </span>
      </SelectTrigger>
      <SelectContent>
        {themes.map((theme) => (
          <SelectItem key={theme} value={theme} className="text-sm font-medium">
            {theme.charAt(0).toUpperCase() + theme.slice(1)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
