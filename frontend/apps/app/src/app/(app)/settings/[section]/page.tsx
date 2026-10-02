import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SectionView } from "@/features/settings/section-view";
import { findSection } from "@/features/settings/sections";
import { googleEnabled } from "@/lib/auth/options";

type Props = { params: Promise<{ section: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const section = findSection((await params).section);
  return { title: section ? `${section.title} · Settings` : "Settings" };
}

export default async function SettingsSectionPage({ params }: Props) {
  const section = findSection((await params).section);
  if (!section) notFound();
  return <SectionView slug={section.slug} googleEnabled={googleEnabled()} />;
}
