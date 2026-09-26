import { redirect } from "next/navigation";

import { DEFAULT_SECTION } from "@/features/settings/sections";

/** `/settings` opens the first section; every section has its own address. */
export default function SettingsPage() {
  redirect(`/settings/${DEFAULT_SECTION}`);
}
