import { SettingsHome } from "@/features/settings/settings-home";

export const metadata = { title: "Settings" };

/** On a phone, the list of sections; wider, the first section (features/settings/settings-home.tsx). */
export default function SettingsPage() {
  return <SettingsHome />;
}
