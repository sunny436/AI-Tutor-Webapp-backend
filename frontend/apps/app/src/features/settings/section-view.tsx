"use client";

import { AppearanceSection } from "./appearance-section";
import { NotificationsSection } from "./notifications-section";
import { PrivacySection } from "./privacy-section";
import { ProfileSection } from "./profile-section";
import type { SectionSlug } from "./sections";

const VIEWS: Record<SectionSlug, () => JSX.Element> = {
  profile: ProfileSection,
  notifications: NotificationsSection,
  appearance: AppearanceSection,
  privacy: PrivacySection,
};

export function SectionView({ slug }: { slug: SectionSlug }) {
  const View = VIEWS[slug];
  return <View />;
}
