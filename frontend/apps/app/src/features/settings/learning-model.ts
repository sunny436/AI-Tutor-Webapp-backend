/** Pure helpers for the learning forms: tested in learning-model.test.ts, no React. */

import type { SubjectItem } from "@/lib/api/types";

type Empty = null | "" | undefined;

function isEmpty(value: unknown): value is Empty {
  return value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
}

function same(a: unknown, b: unknown): boolean {
  if (isEmpty(a) && isEmpty(b)) return true;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * The versioned edit that turns `base` into `draft` for `fields`: a changed field with a value
 * is `set`, a changed field that is now empty is `reset`, anything unchanged is left out.
 */
export function editFor<T extends Record<string, unknown>>(
  base: Partial<T>,
  draft: Partial<T>,
  fields: readonly (keyof T & string)[],
): { set: Partial<T>; reset: (keyof T & string)[] } {
  const set: Partial<T> = {};
  const reset: (keyof T & string)[] = [];
  for (const field of fields) {
    if (same(base[field], draft[field])) continue;
    if (isEmpty(draft[field])) reset.push(field);
    else set[field] = draft[field];
  }
  return { set, reset };
}

export function hasChanges(edit: { set: object; reset: unknown[] }): boolean {
  return Object.keys(edit.set).length > 0 || edit.reset.length > 0;
}

/** One line, trimmed, like the API stores it. */
export function cleanTopic(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** Add a topic unless it is empty, too long, a repeat (any case) or one too many. */
export function addTopic(
  topics: readonly string[],
  text: string,
  limits: { max: number; maxLength: number },
): { topics: string[]; error: string | null } {
  const topic = cleanTopic(text);
  if (!topic) return { topics: [...topics], error: null };
  if (topic.length > limits.maxLength) return { topics: [...topics], error: `Keep a topic under ${limits.maxLength + 1} characters.` };
  if (topics.some((existing) => existing.toLocaleLowerCase() === topic.toLocaleLowerCase()))
    return { topics: [...topics], error: "That topic is already on the list." };
  if (topics.length >= limits.max) return { topics: [...topics], error: `You can list up to ${limits.max} topics.` };
  return { topics: [...topics, topic], error: null };
}

export function moveSubject(items: readonly SubjectItem[], index: number, delta: -1 | 1): SubjectItem[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target] as SubjectItem, next[index] as SubjectItem];
  return next;
}

export function addSubject(items: readonly SubjectItem[], code: string, max: number): SubjectItem[] {
  if (!code || items.length >= max || items.some((item) => item.code === code)) return [...items];
  return [...items, { code, isPriority: false, needsImprovement: false }];
}

export function removeSubject(items: readonly SubjectItem[], code: string): SubjectItem[] {
  return items.filter((item) => item.code !== code);
}

export function toggleSubject(
  items: readonly SubjectItem[],
  code: string,
  flag: "isPriority" | "needsImprovement",
): SubjectItem[] {
  return items.map((item) => (item.code === code ? { ...item, [flag]: !item[flag] } : item));
}
