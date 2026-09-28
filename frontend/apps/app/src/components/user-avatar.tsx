"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@v1/ui/avatar";

import { avatarSrc } from "@/lib/api/identity";
import type { User } from "@/lib/api/types";

/** The student's photo, or their initial: in the sidebar and in the Settings panel. Decorative. */
export function UserAvatar({ user }: { user: User }) {
  const name = user.displayName || user.email;
  const photo = avatarSrc(user);
  return (
    <Avatar aria-hidden className="h-10 w-10 rounded-full border-0">
      {photo && <AvatarImage src={photo} alt="" className="rounded-full" />}
      <AvatarFallback className="rounded-full bg-brand text-base font-semibold text-brand-foreground">
        {name.charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}
