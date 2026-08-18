"use client";

import { env } from "@/env.mjs";
import { ConvexAuthNextjsProvider } from "@convex-dev/auth/nextjs";
import { ConvexReactClient } from "convex/react";
import type { ReactNode } from "react";

// `verbose` floods the browser console on every query/mutation — opt in via env
// when debugging rather than shipping it on by default.
const convex = new ConvexReactClient(env.NEXT_PUBLIC_CONVEX_URL, {
  verbose: process.env.NEXT_PUBLIC_CONVEX_VERBOSE === "true",
});

export function ConvexClientProvider({ children }: { children: ReactNode }) {
  return (
    <ConvexAuthNextjsProvider client={convex}>
      {children}
    </ConvexAuthNextjsProvider>
  );
}
