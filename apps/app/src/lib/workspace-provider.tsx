"use client";

import { api } from "@v1/backend/convex/_generated/api";
import type { Id } from "@v1/backend/convex/_generated/dataModel";
import { useConvexAuth, useMutation, useQuery } from "convex/react";
import { createContext, useContext, useEffect, useState } from "react";

type WS = { _id: Id<"workspaces">; name: string; role: string };
type Ctx = {
  workspaces: WS[];
  current: Id<"workspaces"> | null;
  select: (id: Id<"workspaces">) => void;
};

const WorkspaceCtx = createContext<Ctx>({ workspaces: [], current: null, select: () => {} });
export const useWorkspace = () => useContext(WorkspaceCtx);

/**
 * Holds the current workspace in React context (persisted to localStorage) so the sidebar
 * switcher and every page share it reactively — switching updates all consumers at once.
 */
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  // Gate both calls on the auth state rather than firing them and hoping.
  //
  // `ensureWorkspace` throws "Not authenticated" by design, and this provider
  // mounts on every dashboard page — including the moments around sign-up and
  // sign-out when the Convex client has no token yet. The query would resolve to
  // an empty list, the effect below read that as "this user has no workspace",
  // and the mutation threw. It was harmless to the user but it put a Convex
  // server error in the browser console on every sign-out, which is exactly the
  // noise that hides a real fault later.
  const { isAuthenticated } = useConvexAuth();
  const workspaces = useQuery(api.orgs.myWorkspaces, isAuthenticated ? {} : "skip") as
    | WS[]
    | undefined;
  const ensure = useMutation(api.orgs.ensureWorkspace);
  const [current, setCurrent] = useState<Id<"workspaces"> | null>(null);
  const [ensuring, setEnsuring] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (workspaces === undefined) return;
    if (workspaces.length === 0) {
      if (!ensuring) {
        setEnsuring(true);
        void ensure({}).finally(() => setEnsuring(false));
      }
      return;
    }
    setCurrent((prev) => {
      if (prev && workspaces.some((w) => w._id === prev)) return prev;
      const saved = typeof window !== "undefined" ? window.localStorage.getItem("ws") : null;
      const match = workspaces.find((w) => w._id === saved);
      return match?._id ?? workspaces[0]?._id ?? prev;
    });
  }, [isAuthenticated, workspaces, ensure, ensuring]);

  const select = (id: Id<"workspaces">) => {
    if (typeof window !== "undefined") window.localStorage.setItem("ws", id);
    setCurrent(id);
  };

  return (
    <WorkspaceCtx.Provider value={{ workspaces: workspaces ?? [], current, select }}>
      {children}
    </WorkspaceCtx.Provider>
  );
}
