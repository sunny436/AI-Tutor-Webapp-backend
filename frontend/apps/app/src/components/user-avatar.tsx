"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@v1/ui/avatar";

import { avatarSrc } from "@/lib/api/identity";
import type { User } from "@/lib/api/types";

/** The student's photo, or their initial: in the sidebar and in the Settings panel. Decorative. */
export function UserAvatar({ user }: { user: User }) {
  const name = user.displayName || user.email;
  const photo = avatarSrc(user);
  return (
    <Avatar aria-hidden className="h-10 w-10 rounded-xl border-0 shadow-sm">
      {photo && <AvatarImage src={photo} alt="" className="rounded-xl" />}
      <AvatarFallback className="rounded-xl bg-gradient-to-tr from-streak to-accent-warm text-lg font-bold text-white">
        {name.charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}
