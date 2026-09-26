"use client";

import { AcademicSection } from "./academic-section";
import { AppearanceSection } from "./appearance-section";
import { GoalsSection } from "./goals-section";
import { HelpSection } from "./help-section";
import { NotificationsSection } from "./notifications-section";
import { LearningSection, TutorSection } from "./preferences-sections";
import { PrivacySection } from "./privacy-section";
import { ProfileSection } from "./profile-section";
import { ProgressSection } from "./progress-section";
import type { SectionSlug } from "./sections";
import { SubjectsSection } from "./subjects-section";

const VIEWS: Record<SectionSlug, () => JSX.Element> = {
  profile: ProfileSection,
  academic: AcademicSection,
  goals: GoalsSection,
  learning: LearningSection,
  tutor: TutorSection,
  subjects: SubjectsSection,
  progress: ProgressSection,
  notifications: NotificationsSection,
  appearance: AppearanceSection,
  privacy: PrivacySection,
  help: HelpSection,
};

export function SectionView({ slug }: { slug: SectionSlug }) {
  const View = VIEWS[slug];
  return <View />;
}
