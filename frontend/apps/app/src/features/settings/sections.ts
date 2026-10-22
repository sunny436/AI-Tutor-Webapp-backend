import {
  Bell,
  BookOpen,
  Bot,
  Flame,
  GraduationCap,
  LifeBuoy,
  type LucideIcon,
  Palette,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  Timer,
  TrendingUp,
  UserRound,
} from "lucide-react";

export type SettingsSectionInfo = {
  slug: string;
  title: string;
  description: string;
  icon: LucideIcon;
  /** Other words people search for (Settings > Search). Lower case. */
  keywords: readonly string[];
};

/**
 * The Settings sections, in the product's order: Profile, Academic Profile, Learning Goals,
 * Learning Preferences, AI Tutor, Subjects & Study, Progress & Goals, Study Tracking, Notifications,
 * Appearance & Accessibility, Privacy & Security, Help & Support. Only sections that work
 * end to end are listed; there are no placeholder pages.
 */
export const SETTINGS_SECTIONS = [
  {
    slug: "profile",
    title: "Profile",
    description: "Your photo, name, time zone and email.",
    icon: UserRound,
    keywords: ["photo", "picture", "avatar", "display name", "email address", "time zone", "timezone"],
  },
  {
    slug: "academic",
    title: "Academic Profile",
    description: "Your class, board, medium and academic year.",
    icon: GraduationCap,
    keywords: ["grade", "cbse", "icse", "state board", "school", "language of instruction"],
  },
  {
    slug: "goals",
    title: "Learning Goals",
    description: "What you're working towards, and your study time.",
    icon: Target,
    keywords: ["exam", "exam date", "target score", "difficult topics", "weak topics", "daily goal", "weekly goal", "active time"],
  },
  {
    slug: "learning",
    title: "Learning Preferences",
    description: "Language, depth, pace and examples.",
    icon: SlidersHorizontal,
    keywords: ["hindi", "english", "explanation", "difficulty", "real-world examples", "visual"],
  },
  {
    slug: "tutor",
    title: "AI Tutor",
    description: "How your tutor talks and teaches.",
    icon: Bot,
    keywords: [
      "tone",
      "personality",
      "answer length",
      "hints",
      "step by step",
      "practice questions",
      "mistakes",
      "key concepts",
      "what your tutor is told",
    ],
  },
  {
    slug: "subjects",
    title: "Subjects & Study",
    description: "Your subjects, priorities and what needs work.",
    icon: BookOpen,
    keywords: ["priority", "needs work", "reorder"],
  },
  {
    slug: "progress",
    title: "Progress & Goals",
    description: "Your active time, questions and goals.",
    icon: TrendingUp,
    keywords: ["chart", "goals met", "study time", "active time"],
  },
  {
    slug: "study-tracking",
    title: "Study Tracking",
    description: "What counts as study time: idle, hidden tabs and pauses.",
    icon: Timer,
    keywords: ["study session", "study activity", "idle", "inactivity", "pause", "resume", "hidden tab", "estimate"],
  },
  {
    slug: "streak",
    title: "Learning & Streak",
    description: "Your streak, today's learning and your calendar.",
    icon: Flame,
    keywords: ["streak", "calendar", "heatmap", "learning days", "milestone", "longest streak", "header"],
  },
  {
    slug: "notifications",
    title: "Notifications",
    description: "Study reminders and sign-in alerts by email.",
    icon: Bell,
    keywords: ["daily reminder", "streak reminder", "weekly summary", "security alerts", "unsubscribe", "in the app", "bell"],
  },
  {
    slug: "appearance",
    title: "Appearance & Accessibility",
    description: "Theme, text size, contrast, motion and reading.",
    icon: Palette,
    keywords: ["dark mode", "light mode", "system", "font size", "high contrast", "reduce motion", "animation", "reading comfort"],
  },
  {
    slug: "privacy",
    title: "Privacy & Security",
    description: "Password, signed-in devices and deleting your account.",
    icon: ShieldCheck,
    keywords: ["change password", "sessions", "sign out", "log out", "other devices", "delete account", "data"],
  },
  {
    slug: "help",
    title: "Help & Support",
    description: "Answers, and a way to reach us.",
    icon: LifeBuoy,
    keywords: ["contact", "faq", "question", "bug", "problem", "feedback", "about", "terms", "privacy policy"],
  },
] as const satisfies readonly SettingsSectionInfo[];

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];
export type SectionSlug = SettingsSection["slug"];

export const DEFAULT_SECTION: SectionSlug = "profile";

export function findSection(slug: string | undefined): SettingsSection | undefined {
  return SETTINGS_SECTIONS.find((section) => section.slug === slug);
}

/**
 * Settings > Search: the sections that match every word of `query` (in any case) somewhere in
 * their title, description or keywords, in the usual order. An empty query matches them all.
 */
export function matchSections(query: string): SettingsSection[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [...SETTINGS_SECTIONS];
  return SETTINGS_SECTIONS.filter((section) => {
    const text = [section.title, section.description, ...section.keywords].join(" ").toLowerCase();
    return words.every((word) => text.includes(word));
  });
}
