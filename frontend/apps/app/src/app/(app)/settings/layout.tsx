import type { ReactNode } from "react";

import { SettingsFrame } from "@/features/settings/settings-frame";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return <SettingsFrame>{children}</SettingsFrame>;
}
