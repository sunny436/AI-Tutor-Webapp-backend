import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";

/** The app: the chat, the learning tools and the help pages, inside the sidebar and header. */
export default function MainLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
