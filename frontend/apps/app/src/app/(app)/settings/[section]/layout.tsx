import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { findSection } from "@/features/settings/sections";

/**
 * An unknown section is a real 404. Checked HERE, above the section's loading boundary
 * (loading.tsx): once that boundary streams, the response has already gone out as 200.
 */
export default async function SectionLayout({
  children,
  params,
}: { children: ReactNode; params: Promise<{ section: string }> }) {
  if (!findSection((await params).section)) notFound();
  return children;
}
