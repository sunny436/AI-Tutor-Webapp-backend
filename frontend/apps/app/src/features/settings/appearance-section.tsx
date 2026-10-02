"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import type { JSX } from "react";

import { useAppearance } from "@/components/appearance-provider";
import type { FontSize, Theme } from "@/lib/api/types";
import { ChoiceGroup, SectionHeading, SettingsCard, ToggleRow } from "./primitives";

// Typed by the contract's enums: a new value from the API is a compile error here until named.
const THEME_LABELS: Record<Theme, string> = { system: "System", light: "Light", dark: "Dark" };
const THEME_ICONS: Record<Theme, JSX.Element> = {
  system: <Monitor aria-hidden className="h-4 w-4" />,
  light: <Sun aria-hidden className="h-4 w-4" />,
  dark: <Moon aria-hidden className="h-4 w-4" />,
};
const SIZE_LABELS: Record<FontSize, string> = {
  small: "Small",
  medium: "Default",
  large: "Large",
  x_large: "Extra large",
};

/**
 * Saved to the account as it changes (one versioned PATCH per burst of changes) and applied
 * at once to the whole app, so this page is its own preview.
 */
export function AppearanceSection() {
  const context = useAppearance();
  const { setTheme } = useTheme();
  const appearance = context?.appearance;

  return (
    <>
      <SectionHeading
        title="Appearance & Accessibility"
        description="How PadhAI looks and moves. Saved to your account, so it follows you to every device."
      />
      {!context || !appearance ? (
        <SkeletonGroup label="Loading appearance" className="space-y-3">
          <Skeleton className="h-40 w-full rounded-2xl" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <div className="flex flex-col gap-4">
          <SettingsCard title="Display">
            <ChoiceGroup<Theme>
              legend="Theme"
              description="System follows your device's light or dark setting."
              value={appearance.theme}
              options={(Object.keys(THEME_LABELS) as Theme[]).map((value) => ({
                value,
                label: THEME_LABELS[value],
                icon: THEME_ICONS[value],
              }))}
              onChange={(theme) => {
                setTheme(theme);
                context.change({ theme });
              }}
            />
            <ChoiceGroup<FontSize>
              legend="Text size"
              description="Scales all text and spacing in the app."
              value={appearance.fontSize}
              options={(Object.keys(SIZE_LABELS) as FontSize[]).map((value) => ({ value, label: SIZE_LABELS[value] }))}
              onChange={(fontSize) => context.change({ fontSize })}
            />
          </SettingsCard>
          <SettingsCard title="Accessibility">
            <ToggleRow
              label="High contrast"
              description="Darker secondary text and clearly visible borders, in light and dark."
              checked={appearance.highContrast}
              onCheckedChange={(highContrast) => context.change({ highContrast })}
            />
            <ToggleRow
              label="Reduce motion"
              description="Turns off animations. If your device asks for less motion, that is always respected too."
              checked={appearance.reduceMotion}
              onCheckedChange={(reduceMotion) => context.change({ reduceMotion })}
            />
            <ToggleRow
              label="Comfortable reading"
              description="More space between lines, letters and words in the tutor's answers."
              checked={appearance.readingComfort}
              onCheckedChange={(readingComfort) => context.change({ readingComfort })}
            />
          </SettingsCard>
        </div>
      )}
    </>
  );
}
