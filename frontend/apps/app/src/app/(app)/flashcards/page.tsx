import { notFound } from "next/navigation";

import { FlashcardsView } from "@/features/learning-hub/flashcards-view";
import { previewEnabled } from "@/lib/preview";

export const metadata = { title: "Flashcards" };

// The preview switch is server configuration, read per request (lib/preview.ts).
export const dynamic = "force-dynamic";

/** Preview only: without PREVIEW_FEATURES=1 this page does not exist. */
export default function FlashcardsPage() {
  if (!previewEnabled()) notFound();
  return <FlashcardsView />;
}
