"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import Link from "next/link";

import { describeError } from "@/lib/api/errors";
import { getNotificationPreferences, updateNotificationPreferences } from "@/lib/api/preferences";
import type { NotificationPreferences } from "@/lib/api/types";
import { Notice, SectionHeading, SettingsCard, ToggleRow } from "./primitives";
import { useAutoSaver } from "./use-auto-saver";

/**
 * In the app (the header's bell: everything, reminders switchable) and by email (security and
 * the reminders chosen here). Says plainly when this server is not sending notification emails
 * yet, and when email reminders are waiting for a time zone, rather than letting a switch
 * suggest an email that will not come.
 */
export function NotificationsSection() {
  const { value, change, loadError, retry } = useAutoSaver<NotificationPreferences>({
    load: getNotificationPreferences,
    save: (version, set) =>
      updateNotificationPreferences({
        version,
        set: {
          ...(set.dailyReminder !== undefined && { dailyReminder: set.dailyReminder }),
          ...(set.streakWarning !== undefined && { streakWarning: set.streakWarning }),
          ...(set.weeklySummary !== undefined && { weeklySummary: set.weeklySummary }),
          ...(set.securityAlerts !== undefined && { securityAlerts: set.securityAlerts }),
          ...(set.inAppReminders !== undefined && { inAppReminders: set.inAppReminders }),
        },
      }),
  });

  return (
    <>
      <SectionHeading
        title="Notifications"
        description="What appears in the app's notifications (the bell), and which emails PadhAI sends you."
      />
      {loadError ? (
        <SettingsCard title="Couldn't load your notification settings">
          <p className="text-sm text-text-secondary">{describeError(loadError).message}</p>
          <button
            type="button"
            onClick={retry}
            className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </SettingsCard>
      ) : !value ? (
        <SkeletonGroup label="Loading notification settings" className="space-y-3">
          <Skeleton className="h-56 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <div className="flex flex-col gap-4">
          <SettingsCard
            title="In the app"
            description="Security alerts and streak milestones always appear in the bell at the top of the app."
          >
            <ToggleRow
              label="Reminders in the app"
              description="A gentle streak reminder in the evening of a day you haven't learnt yet, and your study reminders."
              checked={value.inAppReminders}
              onCheckedChange={(inAppReminders) => change({ inAppReminders })}
            />
          </SettingsCard>
          {value.delivery === "paused" && (
            <Notice>
              PadhAI isn't sending notification emails yet. Your choices are saved and will apply as soon as it does.
            </Notice>
          )}
          <SettingsCard title="Study reminders" description="Sent to your email address.">
            {value.remindersNeedTimezone && (
              <Notice tone="warning">
                Reminders are sent at times in your own day, so they need your time zone.{" "}
                <Link href="/settings/profile" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
                  Set your time zone
                </Link>
                .
              </Notice>
            )}
            <ToggleRow
              label="Daily reminder"
              description="At your preferred study time (6 pm until you choose one), only on days you haven't used PadhAI yet."
              checked={value.dailyReminder}
              onCheckedChange={(dailyReminder) => change({ dailyReminder })}
            />
            <ToggleRow
              label="Streak reminder"
              description="In the evening, when a streak of two or more days would end that night."
              checked={value.streakWarning}
              onCheckedChange={(streakWarning) => change({ streakWarning })}
            />
            <ToggleRow
              label="Weekly summary"
              description="On Monday mornings: your active time and questions from the week before."
              checked={value.weeklySummary}
              onCheckedChange={(weeklySummary) => change({ weeklySummary })}
            />
          </SettingsCard>
          <SettingsCard
            title="Security"
            description="A password change is always emailed to you, whatever you choose here."
          >
            <ToggleRow
              label="Sign-in alerts"
              description="When your account is signed in on a new kind of device."
              checked={value.securityAlerts}
              onCheckedChange={(securityAlerts) => change({ securityAlerts })}
            />
          </SettingsCard>
        </div>
      )}
    </>
  );
}
