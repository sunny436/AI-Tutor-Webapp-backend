import { notFound } from "next/navigation";

import { HomeworkView } from "@/features/learning-hub/homework-view";
import { previewEnabled } from "@/lib/preview";

export const metadata = { title: "Homework Helper" };

// The preview switch is server configuration, read per request (lib/preview.ts).
export const dynamic = "force-dynamic";

/** Preview only: without PREVIEW_FEATURES=1 this page does not exist. */
export default function HomeworkPage() {
  if (!previewEnabled()) notFound();
  return <HomeworkView />;
}
