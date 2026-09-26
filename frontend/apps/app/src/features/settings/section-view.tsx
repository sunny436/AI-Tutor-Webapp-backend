"use client";

import { AcademicSection } from "./academic-section";
import { AppearanceSection } from "./appearance-section";
import { GoalsSection } from "./goals-section";
import { NotificationsSection } from "./notifications-section";
import { LearningSection, TutorSection } from "./preferences-sections";
import { PrivacySection } from "./privacy-section";
import { ProfileSection } from "./profile-section";
import type { SectionSlug } from "./sections";
import { SubjectsSection } from "./subjects-section";

const VIEWS: Record<SectionSlug, () => JSX.Element> = {
  profile: ProfileSection,
  academic: AcademicSection,
  goals: GoalsSection,
  learning: LearningSection,
  tutor: TutorSection,
  subjects: SubjectsSection,
  notifications: NotificationsSection,
  appearance: AppearanceSection,
  privacy: PrivacySection,
};

export function SectionView({ slug }: { slug: SectionSlug }) {
  const View = VIEWS[slug];
  return <View />;
}
