"use client";

import { type ReactNode, createContext, useContext, useState } from "react";

import type { User } from "@/lib/api/types";

/**
 * The signed-in user, fetched once on the server by the app layout. Replaces the
 * old app's five separate client queries for the same user.
 */
const UserContext = createContext<{ user: User; setUser: (user: User) => void } | null>(null);

export function UserProvider({ user: initial, children }: { user: User; children: ReactNode }) {
  const [user, setUser] = useState(initial);
  return <UserContext.Provider value={{ user, setUser }}>{children}</UserContext.Provider>;
}

export function useUser() {
  const value = useContext(UserContext);
  if (!value) throw new Error("useUser must be used inside <UserProvider>");
  return value;
}
