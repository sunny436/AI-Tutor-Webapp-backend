import { notFound } from "next/navigation";

import { CoursesView } from "@/features/learning-hub/courses-view";
import { previewEnabled } from "@/lib/preview";

export const metadata = { title: "My Courses" };

// The preview switch is server configuration, read per request (lib/preview.ts).
export const dynamic = "force-dynamic";

/** Preview only: without PREVIEW_FEATURES=1 this page does not exist. */
export default function CoursesPage() {
  if (!previewEnabled()) notFound();
  return <CoursesView />;
}
