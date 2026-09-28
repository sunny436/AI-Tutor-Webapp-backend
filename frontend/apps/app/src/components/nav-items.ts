import { BookOpen, FileEdit, Layers, Lightbulb, type LucideIcon, MessageSquare, Sparkles } from "lucide-react";

/**
 * The Learning Hub: every tool in the sidebar, in order, with the line under its
 * name and the colours of its icon chip. The header reads the same list, so a
 * tool's title is written once.
 *
 * Only the AI Tutor (the chat) is real today. The others are UI ahead of their
 * backend, marked `preview`: they are listed, and their pages exist, only when
 * preview features are on (lib/preview.ts).
 */
export type NavItem = {
  id: "tutor" | "courses" | "homework" | "summarizer" | "course-creator" | "flashcards";
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  /** The icon chip at rest: the tool's own colour, from its soft/solid token pair. */
  accent: string;
  preview: boolean;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    id: "tutor",
    href: "/",
    label: "AI Tutor",
    description: "24/7 Personal Doubts Solver",
    icon: MessageSquare,
    accent: "bg-brand-soft text-brand",
    preview: false,
  },
  {
    id: "courses",
    href: "/courses",
    label: "My Courses",
    description: "CBSE & ICSE Syllabus Tree",
    icon: BookOpen,
    accent: "bg-info-soft text-info",
    preview: true,
  },
  {
    id: "homework",
    href: "/homework",
    label: "Homework Helper",
    description: "Snap & Solve Math / Science",
    icon: FileEdit,
    accent: "bg-success-soft text-success",
    preview: true,
  },
  {
    id: "summarizer",
    href: "/summarizer",
    label: "Summarizer",
    description: "2-Min Chapter Recaps & Notes",
    icon: Lightbulb,
    accent: "bg-warning-soft text-warning",
    preview: true,
  },
  {
    id: "course-creator",
    href: "/course-creator",
    label: "Course Creator",
    description: "Custom AI Study Roadmap Generator",
    icon: Sparkles,
    accent: "bg-accent-purple-soft text-accent-purple",
    preview: true,
  },
  {
    id: "flashcards",
    href: "/flashcards",
    label: "Flashcards",
    description: "Active Recall & Spaced Repetition",
    icon: Layers,
    accent: "bg-accent-pink-soft text-accent-pink",
    preview: true,
  },
];

/** The tools a reader may see: all of them with preview features on, else only the real ones. */
export function visibleNavItems(preview: boolean): readonly NavItem[] {
  return preview ? NAV_ITEMS : NAV_ITEMS.filter((item) => !item.preview);
}

/**
 * The sidebar's Learning Hub: the tools besides the chat. The chat is already the sidebar's
 * "Ask New Doubt" and chat list, so it is not listed again; with no other tool, there is no hub.
 */
export function hubItems(preview: boolean): readonly NavItem[] {
  return visibleNavItems(preview).filter((item) => item.id !== "tutor");
}

/** The tutor owns `/` and every conversation (`/c/<id>`); a tool owns its path and below. */
export function isActive(item: NavItem, pathname: string | null): boolean {
  const path = pathname ?? "";
  if (item.href === "/") return path === "/" || path.startsWith("/c/");
  return path === item.href || path.startsWith(`${item.href}/`);
}

/** The tool whose page is on screen, if any. */
export function navItemFor(pathname: string | null): NavItem | null {
  return NAV_ITEMS.find((item) => isActive(item, pathname)) ?? null;
}
