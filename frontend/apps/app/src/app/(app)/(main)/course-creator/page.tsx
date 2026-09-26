import { notFound } from "next/navigation";

import { CourseCreatorView } from "@/features/learning-hub/course-creator-view";
import { previewEnabled } from "@/lib/preview";

export const metadata = { title: "Course Creator" };

// The preview switch is server configuration, read per request (lib/preview.ts).
export const dynamic = "force-dynamic";

/** Preview only: without PREVIEW_FEATURES=1 this page does not exist. */
export default function CourseCreatorPage() {
  if (!previewEnabled()) notFound();
  return <CourseCreatorView />;
}
