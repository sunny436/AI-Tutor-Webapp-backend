import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SectionView } from "@/features/settings/section-view";
import { findSection } from "@/features/settings/sections";

type Props = { params: { section: string } };

export function generateMetadata({ params }: Props): Metadata {
  const section = findSection(params.section);
  return { title: section ? `${section.title} · Settings` : "Settings" };
}

export default function SettingsSectionPage({ params }: Props) {
  const section = findSection(params.section);
  if (!section) notFound();
  return <SectionView slug={section.slug} />;
}
