import { notFound } from "next/navigation";

import { SummarizerView } from "@/features/learning-hub/summarizer-view";
import { previewEnabled } from "@/lib/preview";

export const metadata = { title: "Summarizer" };

// The preview switch is server configuration, read per request (lib/preview.ts).
export const dynamic = "force-dynamic";

/** Preview only: without PREVIEW_FEATURES=1 this page does not exist. */
export default function SummarizerPage() {
  if (!previewEnabled()) notFound();
  return <SummarizerView />;
}
