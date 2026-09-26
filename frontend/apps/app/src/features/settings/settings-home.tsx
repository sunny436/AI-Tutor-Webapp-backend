"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { DEFAULT_SECTION } from "./sections";
import { SettingsPanel } from "./settings-panel";

/** Tailwind's `md`: the workspace shows the panel beside the section from here up. */
export const WIDE_QUERY = "(min-width: 768px)";

/**
 * `/settings`. On a phone, the list of sections (each opens as its own screen). Where the panel
 * sits beside the section (768px and up) the list is already on screen, so the first section
 * opens instead: replaced, not pushed, so Back doesn't come back here to be sent on again.
 */
export function SettingsHome() {
  const router = useRouter();
  useEffect(() => {
    const wide = window.matchMedia(WIDE_QUERY);
    const openFirst = () => {
      if (wide.matches) router.replace(`/settings/${DEFAULT_SECTION}`);
    };
    openFirst();
    wide.addEventListener("change", openFirst);
    return () => wide.removeEventListener("change", openFirst);
  }, [router]);

  return (
    <div className="md:hidden">
      <SettingsPanel variant="list" />
    </div>
  );
}
