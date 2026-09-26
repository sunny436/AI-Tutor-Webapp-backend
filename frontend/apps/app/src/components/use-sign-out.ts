"use client";

import { useState } from "react";
import { toast } from "sonner";

import { useStores } from "@/features/chat/chat-context";
import { navigationGuard } from "@/features/navigation/navigation-guard";
import { logout } from "@/lib/api/auth";
import { describeError } from "@/lib/api/errors";
import { cacheAttributes } from "@/lib/appearance";

/**
 * Log out (the sidebar and the Settings panel). Unsaved edits are asked about FIRST: asking
 * after signing out would leave "Stay" on a page whose session is gone.
 */
export function useSignOut() {
  const { chat } = useStores();
  const [signingOut, setSigningOut] = useState(false);

  const signOut = async () => {
    if (!navigationGuard.confirmLeave()) return;
    setSigningOut(true);
    try {
      await logout();
    } catch (error) {
      navigationGuard.stay(); // still here: keep protecting the edit
      setSigningOut(false);
      toast.error(describeError(error).message);
      return;
    }
    chat.reset();
    cacheAttributes(null); // the next person on this device starts from the defaults
    // A full load leaves nothing of the old session in memory.
    window.location.assign("/login");
  };

  return { signOut, signingOut };
}
