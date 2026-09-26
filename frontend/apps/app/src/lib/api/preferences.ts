/** Appearance and notification preferences: two versioned resources (docs/api-contract.md). */

import { callRoute } from "./http";
import type {
  Appearance,
  AppearanceValues,
  NotificationPreferences,
  NotificationValues,
  VersionedEdit,
} from "./types";

export function getAppearance(): Promise<Appearance> {
  return callRoute("GET /v1/me/appearance");
}

export function updateAppearance(edit: VersionedEdit<AppearanceValues, keyof AppearanceValues>): Promise<Appearance> {
  return callRoute("PATCH /v1/me/appearance", {
    body: { version: edit.version, set: edit.set ?? {}, reset: edit.reset ?? [] },
  });
}

export function getNotificationPreferences(): Promise<NotificationPreferences> {
  return callRoute("GET /v1/notifications/preferences");
}

export function updateNotificationPreferences(
  edit: VersionedEdit<NotificationValues, keyof NotificationValues>,
): Promise<NotificationPreferences> {
  return callRoute("PATCH /v1/notifications/preferences", {
    body: { version: edit.version, set: edit.set ?? {}, reset: edit.reset ?? [] },
  });
}
