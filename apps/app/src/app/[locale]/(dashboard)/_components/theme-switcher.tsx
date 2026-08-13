"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@v1/ui/select";
import { cn } from "@v1/ui/utils";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeSwitcher({ triggerClass }: { triggerClass?: string }) {
  const { theme: currentTheme, setTheme, themes } = useTheme();
  // Avoid hydration mismatch: the theme is unknown on the server, so only show
  // the theme-dependent icon/label after the component has mounted on the client.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const shown = mounted ? currentTheme : undefined;

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
      onValueChange={(theme) => setTheme(theme as (typeof themes)[number])}
    >
      <SelectTrigger
        className={cn(
          "h-6 rounded border-primary/20 bg-secondary !px-2 hover:border-primary/40",
          triggerClass,
        )}
      >
        <div className="flex items-start gap-2">
          {shown === "light" ? (
            <Sun className="h-[14px] w-[14px]" />
          ) : shown === "dark" ? (
            <Moon className="h-[14px] w-[14px]" />
          ) : (
            <Monitor className="h-[14px] w-[14px]" />
          )}
          {shown && (
            <span className="text-xs font-medium">
              {shown.charAt(0).toUpperCase() + shown.slice(1)}
            </span>
          )}
        </div>
      </SelectTrigger>
      <SelectContent>
        {themes.map((theme) => (
          <SelectItem
            key={theme}
            value={theme}
            className={`text-sm font-medium text-primary/60 ${theme === shown ? "text-primary" : ""}`}
          >
            {theme && theme.charAt(0).toUpperCase() + theme.slice(1)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// `ThemeSwitcherHome` lived here — a row of three icon buttons, exported and
// imported by nothing since the starter. It also had no accessible name on any
// button, so it announced as "button, button, button". Removed rather than
// fixed; the Select above is the one theme control, and Stage 2 gives it a home
// on the screens that currently cannot reach it (login, onboarding, 404, error).
