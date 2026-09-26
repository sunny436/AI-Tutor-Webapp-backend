"use client";

import { Button } from "@v1/ui/button";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, describeError } from "@/lib/api/errors";
import { getSubjects, replaceSubjects } from "@/lib/api/learning";
import { SUBJECTS_MAX, type SubjectItem, type SubjectList } from "@/lib/api/types";
import { catalogOptions, useCatalog } from "./learning-data";
import { addSubject, moveSubject, removeSubject, toggleSubject } from "./learning-model";
import { Notice, SectionHeading, SettingsCard } from "./primitives";
import { selectClass } from "./profile-form";
import { useUnsavedChanges } from "./use-unsaved-changes";

type Focus = { code: string; action: "up" | "down" } | null;

/**
 * The subjects the student takes, in the order they want them, each optionally marked as a
 * priority or as needing work. Edited as a whole list and saved as one versioned PUT.
 * Reordering works from the keyboard: focus stays on the moved subject's button.
 */
export function SubjectsSection() {
  const { catalog, error: catalogError, retry: retryCatalog } = useCatalog();
  const [saved, setSaved] = useState<SubjectList | null>(null);
  const [items, setItems] = useState<SubjectItem[]>([]);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [adding, setAdding] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const addId = useId();
  const dirty = saved !== null && JSON.stringify(items) !== JSON.stringify(saved.items);
  useUnsavedChanges(dirty);

  // One fetch per attempt.
  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    getSubjects().then(
      (list) => {
        if (cancelled) return;
        setSaved(list);
        setItems(list.items);
      },
      (failure) => !cancelled && setLoadError(failure),
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // After a move, the moved subject's button keeps the focus (React moved its row).
  useEffect(() => {
    if (!focus) return;
    const own = buttons.current.get(`${focus.code}:${focus.action}`);
    const other = buttons.current.get(`${focus.code}:${focus.action === "up" ? "down" : "up"}`);
    (own && !own.disabled ? own : other)?.focus();
    setFocus(null);
  }, [focus]);

  const nameOf = (code: string) => catalog?.subjects.find((entry) => entry.code === code);
  const available = catalog
    ? catalogOptions(catalog.subjects, null).filter((entry) => !items.some((item) => item.code === entry.code))
    : [];

  const move = (index: number, delta: -1 | 1, code: string) => {
    setItems((list) => moveSubject(list, index, delta));
    setFocus({ code, action: delta < 0 ? "up" : "down" });
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!saved || pending || !dirty) return;
    setPending(true);
    setNotice(null);
    try {
      const next = await replaceSubjects(saved.version, items);
      setSaved(next);
      setItems(next.items);
      toast.success("Subjects saved.");
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "version_conflict" && failure.current) {
        setSaved(failure.current as SubjectList);
        setNotice("Your subjects were just changed somewhere else. Your list is still here: check it and save again.");
      } else {
        toast.error(describeError(failure).message);
      }
    } finally {
      setPending(false);
    }
  };

  const error = catalogError ?? loadError;

  return (
    <>
      <SectionHeading
        title="Subjects & Study"
        description="The subjects you take, in the order you want them. The tutor pays extra attention to priorities and to subjects that need work."
      />
      {error ? (
        <SettingsCard title="Couldn't load your subjects">
          <p className="text-sm text-text-secondary">{describeError(error).message}</p>
          <button
            type="button"
            onClick={() => (catalogError ? retryCatalog() : setAttempt((count) => count + 1))}
            className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </SettingsCard>
      ) : !catalog || !saved ? (
        <SkeletonGroup label="Loading your subjects">
          <Skeleton className="h-72 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <form onSubmit={save}>
          <SettingsCard
            title="Your subjects"
            description={`Up to ${SUBJECTS_MAX}.`}
            footer={
              <>
                {dirty && (
                  <Button type="button" size="sm" variant="ghost" onClick={() => setItems(saved.items)} disabled={pending}>
                    Cancel
                  </Button>
                )}
                <Button type="submit" size="sm" disabled={pending || !dirty}>
                  {pending ? "Saving…" : "Save"}
                </Button>
              </>
            }
          >
            {notice && <Notice tone="warning">{notice}</Notice>}
            <div className="flex flex-col gap-1.5">
              <label htmlFor={addId} className="text-sm font-bold text-foreground">
                Add a subject
              </label>
              <div className="flex w-full gap-2 sm:max-w-[28rem]">
                <select
                  id={addId}
                  value={adding}
                  onChange={(event) => setAdding(event.target.value)}
                  className={selectClass}
                  disabled={items.length >= SUBJECTS_MAX}
                >
                  <option value="">Choose a subject</option>
                  {available.map((entry) => (
                    <option key={entry.code} value={entry.code}>
                      {entry.name}
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!adding || items.length >= SUBJECTS_MAX}
                  onClick={() => {
                    setItems((list) => addSubject(list, adding, SUBJECTS_MAX));
                    setAdding("");
                  }}
                >
                  Add
                </Button>
              </div>
            </div>

            {items.length === 0 ? (
              <p className="text-sm text-text-secondary">No subjects yet.</p>
            ) : (
              <ol aria-label="Your subjects" className="divide-y divide-border rounded-xl border border-border">
                {items.map((item, index) => {
                  const entry = nameOf(item.code);
                  const name = entry?.name ?? item.code;
                  return (
                    <li key={item.code} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5">
                      <span className="min-w-0 flex-1 text-sm font-bold text-foreground">
                        <span className="mr-2 font-normal text-text-secondary">{index + 1}.</span>
                        {name}
                        {entry?.deprecated && <span className="ml-1 font-normal text-text-secondary">(no longer offered)</span>}
                      </span>
                      <label className="flex items-center gap-1.5 text-sm text-text-secondary">
                        <input
                          type="checkbox"
                          checked={item.isPriority}
                          onChange={() => setItems((list) => toggleSubject(list, item.code, "isPriority"))}
                          aria-label={`Priority: ${name}`}
                          className="h-4 w-4 accent-[hsl(var(--brand))]"
                        />
                        Priority
                      </label>
                      <label className="flex items-center gap-1.5 text-sm text-text-secondary">
                        <input
                          type="checkbox"
                          checked={item.needsImprovement}
                          onChange={() => setItems((list) => toggleSubject(list, item.code, "needsImprovement"))}
                          aria-label={`Needs work: ${name}`}
                          className="h-4 w-4 accent-[hsl(var(--brand))]"
                        />
                        Needs work
                      </label>
                      <span className="flex gap-1">
                        <Button
                          ref={(node) => {
                            if (node) buttons.current.set(`${item.code}:up`, node);
                            else buttons.current.delete(`${item.code}:up`);
                          }}
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8"
                          aria-label={`Move ${name} up`}
                          disabled={index === 0}
                          onClick={() => move(index, -1, item.code)}
                        >
                          <ArrowUp aria-hidden className="h-4 w-4" />
                        </Button>
                        <Button
                          ref={(node) => {
                            if (node) buttons.current.set(`${item.code}:down`, node);
                            else buttons.current.delete(`${item.code}:down`);
                          }}
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8"
                          aria-label={`Move ${name} down`}
                          disabled={index === items.length - 1}
                          onClick={() => move(index, 1, item.code)}
                        >
                          <ArrowDown aria-hidden className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8"
                          aria-label={`Remove ${name}`}
                          onClick={() => setItems((list) => removeSubject(list, item.code))}
                        >
                          <X aria-hidden className="h-4 w-4" />
                        </Button>
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </SettingsCard>
        </form>
      )}
    </>
  );
}
