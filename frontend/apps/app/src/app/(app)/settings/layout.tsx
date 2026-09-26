import type { ReactNode } from "react";

import { SettingsWorkspace } from "@/features/settings/settings-workspace";

/** Settings is its own workspace, not a page of the app shell (that is `(main)/`). */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  return <SettingsWorkspace>{children}</SettingsWorkspace>;
}
