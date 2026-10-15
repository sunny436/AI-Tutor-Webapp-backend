"use client";

import type { JSX } from "react";

import { AcademicSection } from "./academic-section";
import { AppearanceSection } from "./appearance-section";
import { GoalsSection } from "./goals-section";
import { HelpSection } from "./help-section";
import { NotificationsSection } from "./notifications-section";
import { LearningSection, TutorSection } from "./preferences-sections";
import { PrivacySection } from "./privacy-section";
import { ProfileSection } from "./profile-section";
import { ProgressSection } from "./progress-section";
import { StreakSection } from "./streak-section";
import { StudyTrackingSection } from "./study-tracking-section";
import type { SectionSlug } from "./sections";
import { SubjectsSection } from "./subjects-section";

/** What a section may need from the server: whether Google sign-in is configured (Privacy). */
export type SectionProps = { googleEnabled: boolean };

const VIEWS: Record<SectionSlug, (props: SectionProps) => JSX.Element> = {
  profile: ProfileSection,
  academic: AcademicSection,
  goals: GoalsSection,
  learning: LearningSection,
  tutor: TutorSection,
  subjects: SubjectsSection,
  progress: ProgressSection,
  "study-tracking": StudyTrackingSection,
  streak: StreakSection,
  notifications: NotificationsSection,
  appearance: AppearanceSection,
  privacy: PrivacySection,
  help: HelpSection,
};

export function SectionView({ slug, googleEnabled }: { slug: SectionSlug } & SectionProps) {
  const View = VIEWS[slug];
  return <View googleEnabled={googleEnabled} />;
}
