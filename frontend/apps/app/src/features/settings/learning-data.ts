"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import { getCatalog, getLearnerProfile, updateLearnerProfile } from "@/lib/api/learning";
import type {
  AcademicCatalog,
  CatalogEntry,
  LearnerProfile,
  LearnerProfileField,
  LearnerProfileValues,
} from "@/lib/api/types";

let catalogRequest: Promise<AcademicCatalog> | null = null;

/** The academic catalog, fetched once per page load and shared by every section. */
export function useCatalog() {
  const [catalog, setCatalog] = useState<AcademicCatalog | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  // One fetch per attempt.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    catalogRequest ??= getCatalog().catch((failure) => {
      catalogRequest = null; // a later attempt tries again
      throw failure;
    });
    catalogRequest.then(
      (loaded) => !cancelled && setCatalog(loaded),
      (failure) => !cancelled && setError(failure),
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return { catalog, error, retry: () => setAttempt((count) => count + 1) };
}

/**
 * The options for a catalog field: every offered entry, plus a deprecated one only while it is
 * the current value (the API accepts a deprecated code only when it is kept, not chosen anew).
 */
export function catalogOptions(entries: readonly CatalogEntry[], current: string | null | undefined): CatalogEntry[] {
  return entries.filter((entry) => !entry.deprecated || entry.code === current);
}

export class ProfileConflict extends Error {
  constructor() {
    super("The learner profile was changed somewhere else.");
  }
}

/**
 * The learner profile (GET/PATCH /v1/learning/profile). `save` sends a versioned edit; on a
 * 409 it adopts the profile as it is now and throws ProfileConflict, so the form keeps the
 * user's edit and asks them to check it and save again.
 */
export function useLearnerProfile() {
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  // One fetch per attempt.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    getLearnerProfile().then(
      (loaded) => !cancelled && setProfile(loaded),
      (failure) => !cancelled && setError(failure),
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const save = useCallback(
    async (set: Partial<LearnerProfileValues>, reset: LearnerProfileField[]): Promise<LearnerProfile> => {
      if (!profile) throw new Error("The profile is not loaded yet.");
      try {
        const next = await updateLearnerProfile({ version: profile.version, set, reset });
        setProfile(next);
        return next;
      } catch (failure) {
        if (failure instanceof ApiError && failure.code === "version_conflict" && failure.current) {
          setProfile(failure.current as LearnerProfile);
          throw new ProfileConflict();
        }
        throw failure;
      }
    },
    [profile],
  );

  return { profile, error, save, retry: () => setAttempt((count) => count + 1) };
}
