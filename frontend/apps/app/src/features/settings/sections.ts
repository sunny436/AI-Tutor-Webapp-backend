import {
  Bell,
  BookOpen,
  Bot,
  GraduationCap,
  LifeBuoy,
  type LucideIcon,
  Palette,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  TrendingUp,
  UserRound,
} from "lucide-react";

export type SettingsSectionInfo = {
  slug: string;
  title: string;
  description: string;
  icon: LucideIcon;
};

/**
 * The Settings sections, in the product's order: Profile, Academic Profile, Learning Goals,
 * Learning Preferences, AI Tutor, Subjects & Study, Progress & Goals, Notifications,
 * Appearance & Accessibility, Privacy & Security, Help & Support. Only sections that work
 * end to end are listed; there are no placeholder pages.
 */
export const SETTINGS_SECTIONS = [
  { slug: "profile", title: "Profile", description: "Your photo, name, time zone and email.", icon: UserRound },
  {
    slug: "academic",
    title: "Academic Profile",
    description: "Your class, board, medium and academic year.",
    icon: GraduationCap,
  },
  {
    slug: "goals",
    title: "Learning Goals",
    description: "What you're working towards, and your study time.",
    icon: Target,
  },
  {
    slug: "learning",
    title: "Learning Preferences",
    description: "Language, depth, pace and examples.",
    icon: SlidersHorizontal,
  },
  { slug: "tutor", title: "AI Tutor", description: "How your tutor talks and teaches.", icon: Bot },
  {
    slug: "subjects",
    title: "Subjects & Study",
    description: "Your subjects, priorities and what needs work.",
    icon: BookOpen,
  },
  {
    slug: "progress",
    title: "Progress & Goals",
    description: "Your active time, questions and streak.",
    icon: TrendingUp,
  },
  {
    slug: "notifications",
    title: "Notifications",
    description: "Study reminders and sign-in alerts by email.",
    icon: Bell,
  },
  {
    slug: "appearance",
    title: "Appearance & Accessibility",
    description: "Theme, text size, contrast, motion and reading.",
    icon: Palette,
  },
  {
    slug: "privacy",
    title: "Privacy & Security",
    description: "Password, signed-in devices and deleting your account.",
    icon: ShieldCheck,
  },
  { slug: "help", title: "Help & Support", description: "Answers, and a way to reach us.", icon: LifeBuoy },
] as const satisfies readonly SettingsSectionInfo[];

export type SectionSlug = (typeof SETTINGS_SECTIONS)[number]["slug"];

export const DEFAULT_SECTION: SectionSlug = "profile";

export function findSection(slug: string | undefined): (typeof SETTINGS_SECTIONS)[number] | undefined {
  return SETTINGS_SECTIONS.find((section) => section.slug === slug);
}
