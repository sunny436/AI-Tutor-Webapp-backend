"use client";

// The ONLY importer of @goujon/react-calendar-heatmap (a React wrapper of DKirwan's
// calendar-heatmap, MIT; the upstream is not maintained). Replacing the library means changing
// this file (and its stylesheet) alone: the rest of the app passes learning days in and gets
// day clicks out.
import { CalendarHeatmap } from "@goujon/react-calendar-heatmap";
import { useTheme } from "next-themes";
import { type KeyboardEvent, type UIEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LearningDay } from "@/lib/api/types";
import "./learning-activity-calendar.css";

/** Intensity levels 0 (no learning) to 4 (the server's `intensity`). */
const LEVELS = 4;

/**
 * The library draws a fixed width (its `fitWidth` ignores the container), so the size is worked
 * out here from the calendar's own width: a year is at most 54 week columns, each a cell plus
 * 2px of padding, inside 20px margins either side. The year fits when its days can be 6px or
 * more; narrower (a phone), 10px days, easier to tap, scroll sideways instead.
 */
const WEEKS = 54;
const CELL_PADDING = 2;
const MARGINS = 40;
function layout(available: number) {
  const fitted = Math.floor((available - MARGINS) / WEEKS) - CELL_PADDING;
  const cell = fitted >= 6 ? Math.min(14, fitted) : 10;
  const grid = WEEKS * (cell + CELL_PADDING);
  // The legend (Less, four squares, More) sits under the grid's right end: its width places it there.
  return { cell, width: Math.max(available - MARGINS, grid), legend: 5 * (cell + CELL_PADDING) + 34 };
}

/** Rows 0, 2, 4 and 6 (Monday, Wednesday, Friday, Sunday) get a label; Sunday's is left empty. */
const DAY_LABELS = { day: { start: 0, interval: 2 } };
const DAY_INITIAL = new Intl.DateTimeFormat(undefined, { weekday: "narrow" });
/** Arrow keys over the grid: a column is a week (Monday at the top). */
const MOVES: Record<string, number> = { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -7, ArrowRight: 7 };

/** "YYYY-MM-DD" as a calendar date where the student is (never shifted a day by UTC parsing). */
function parseDay(value: Date | string | number): Date {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year as number, (month as number) - 1, day as number);
  }
  return new Date(value);
}

export function dayKey(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The theme's own colours (CSS tokens are "H S% L%" triples), read when the theme changes. */
function tokenColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value ? `hsl(${value.split(/\s+/).join(", ")})` : fallback;
}

function interactionsText(interactions: number): string {
  return `${interactions} learning interaction${interactions === 1 ? "" : "s"}`;
}

function describeDay(date: Date, interactions: number): string {
  const day = date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return `${day}: ${interactions ? `learning day, ${interactionsText(interactions)}` : "no learning"}`;
}

function shortDay(date: Date, interactions: number): string {
  const day = date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return `${day} · ${interactions ? interactionsText(interactions) : "No learning"}`;
}

/**
 * After each drawing by the library, which makes an <svg role="img"> holding a focusable button
 * per day (every day a Tab stop, and buttons inside an image that screen readers can't reach):
 * - the grid becomes a labelled group with ONE Tab stop (the chosen day, else today), which the
 *   arrow keys move; Enter or Space shows the day, as a click does;
 * - a first month too short for its label loses it (it would print over the next one);
 * - a new drawing is scrolled to its end, today: on a narrow screen the year scrolls sideways.
 */
function afterDraw(root: HTMLElement, current: number | null): void {
  const svg = root.querySelector("svg.calendar-heatmap");
  const cells = [...root.querySelectorAll<SVGRectElement>("rect.day-cell")];
  if (!svg || !cells.length) return;
  const stop = current !== null && current < cells.length ? current : cells.length - 1;
  cells.forEach((cell, index) => cell.setAttribute("tabindex", index === stop ? "0" : "-1"));
  if (svg.getAttribute("role") === "group") return;
  svg.setAttribute("role", "group");
  const [first, second] = svg.querySelectorAll<SVGTextElement>("text.month-name");
  if (first && second && first.getBBox().x + first.getBBox().width + 4 > second.getBBox().x) first.remove();
  root.scrollLeft = root.scrollWidth;
}

/** The library's tooltip, moved to the day's centre and kept inside the drawing (below, else above). */
function placeTooltip(day: EventTarget | null): void {
  requestAnimationFrame(() => {
    const svg = day instanceof SVGRectElement ? day.ownerSVGElement : null;
    const tip = svg?.parentElement?.querySelector<HTMLElement>(".day-cell-tooltip");
    const frame = tip?.offsetParent;
    if (!svg || !tip || !(frame instanceof HTMLElement)) return;
    const origin = frame.getBoundingClientRect();
    const area = svg.getBoundingClientRect();
    const cell = (day as SVGRectElement).getBoundingClientRect();
    const left = cell.left - origin.left + cell.width / 2 - tip.offsetWidth / 2;
    tip.style.left = `${Math.max(0, Math.min(left, area.width - tip.offsetWidth))}px`;
    const below = cell.bottom - origin.top + 6;
    const fits = below + tip.offsetHeight <= area.bottom - origin.top;
    tip.style.top = `${fits ? below : cell.top - origin.top - tip.offsetHeight - 6}px`;
  });
}

/**
 * A year of learning days as a contribution calendar. `days` are the server's daily totals;
 * `onSelect` gets the day clicked (or chosen from the keyboard).
 */
export function LearningActivityCalendar({
  days,
  start,
  onSelect,
}: {
  days: LearningDay[];
  start: string;
  onSelect: (date: string) => void;
}) {
  const { resolvedTheme } = useTheme();
  const [colors, setColors] = useState<string[] | null>(null);
  const [available, setAvailable] = useState(0);
  // Which sides have more of the year scrolled out of view (a narrow screen): faded, with a hint.
  const [more, setMore] = useState<Sides>(null);
  const box = useRef<HTMLDivElement>(null);
  const focused = useRef<number | null>(null);
  const onScroll = useCallback((event: UIEvent<HTMLDivElement>) => setMore(hiddenSides(event.currentTarget)), []);

  useEffect(() => {
    // Recomputed after the theme class lands on <html>.
    const frame = requestAnimationFrame(() =>
      setColors([tokenColor("--surface-2", "#eef1f4"), tokenColor("--brand", "#4f6f8f")]),
    );
    return () => cancelAnimationFrame(frame);
  }, [resolvedTheme]);

  useEffect(() => {
    const root = box.current;
    if (!root || !colors) return;
    const resize = new ResizeObserver(([entry]) => {
      setAvailable(Math.floor(entry?.contentRect.width ?? 0));
      setMore(hiddenSides(root));
    });
    resize.observe(root);
    // The library redraws on a new size or new data: prepare each drawing.
    const drawn = new MutationObserver(() => {
      afterDraw(root, focused.current);
      setMore(hiddenSides(root));
    });
    drawn.observe(root, { childList: true, subtree: true });
    // A new theme redraws in the library's own effect, which runs before this one: prepare that drawing now.
    afterDraw(root, focused.current);
    return () => {
      resize.disconnect();
      drawn.disconnect();
    };
  }, [colors]);

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const cells = [...(box.current?.querySelectorAll<SVGRectElement>("rect.day-cell") ?? [])];
    const index = cells.indexOf(event.target as SVGRectElement);
    if (index < 0) return;
    const move = MOVES[event.key];
    const next =
      move !== undefined ? index + move : event.key === "Home" ? 0 : event.key === "End" ? cells.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const target = cells[Math.max(0, Math.min(cells.length - 1, next))] as SVGRectElement;
    cells[index]?.setAttribute("tabindex", "-1");
    target.setAttribute("tabindex", "0");
    focused.current = cells.indexOf(target);
    target.focus();
  }, []);

  const interactions = useMemo(() => new Map(days.map((day) => [day.date, day.interactions])), [days]);
  const data = useMemo(() => days.map((day) => ({ date: day.date, count: day.intensity })), [days]);
  // Stable props: the library redraws on any change, which would drop the focused day.
  const formatters = useMemo(
    () => ({
      tooltip: (date: Date) => shortDay(date, interactions.get(dayKey(date)) ?? 0),
      // Monday, Wednesday and Friday, as initials.
      dayLabel: (weekday: number) => (weekday === 0 ? "" : DAY_INITIAL.format(new Date(2020, 5, 7 + weekday))),
      ariaLabel: (date: Date) => describeDay(date, interactions.get(dayKey(date)) ?? 0),
      legend: { less: "Less", more: "More" },
    }),
    [interactions],
  );
  const showTooltip = useCallback((_: unknown, event: Event) => placeTooltip(event.target), []);
  const choose = useCallback(
    ({ date }: { date: Date }) => {
      // The day chosen becomes the grid's Tab stop.
      const root = box.current;
      const cells = [...(root?.querySelectorAll("rect.day-cell") ?? [])];
      const index = cells.findIndex((cell) => cell === document.activeElement);
      if (root && index >= 0) {
        focused.current = index;
        afterDraw(root, index);
      }
      onSelect(dayKey(date));
    },
    [onSelect],
  );

  if (!colors) return <div className="h-40" aria-hidden />;
  const size = layout(available);
  return (
    <>
      <div
        ref={box}
        className="learning-calendar scrollbar-subtle overflow-x-auto"
        data-more={more ?? undefined}
        onKeyDown={onKeyDown}
        onScroll={onScroll}
      >
        {available > 0 && (
          <CalendarHeatmap
            key={`${resolvedTheme}-${colors.join()}`}
            data={data}
            startDate={start}
            dateParser={parseDay}
            weekStart="monday"
            width={size.width}
            cellSize={size.cell}
            cellPadding={CELL_PADDING}
            legendWidth={size.legend}
            max={LEVELS}
            colorRange={colors}
            tooltipEnabled
            legendEnabled
            accessibilityTable={false}
            labels={DAY_LABELS}
            ariaLabel="Learning days in the last year"
            ariaDescription="Use the arrow keys to move between days, and Enter to see a day."
            formatters={formatters}
            onHover={showTooltip}
            onFocus={showTooltip}
            onClick={choose}
          />
        )}
      </div>
      {more && <p className="mt-1 text-2xs text-text-secondary">Scroll sideways to see the whole year.</p>}
    </>
  );
}

type Sides = "left" | "right" | "both" | null;

/** The sides of the year that are scrolled out of view, if any. */
function hiddenSides(root: HTMLElement): Sides {
  const left = root.scrollLeft > 2;
  const right = root.scrollLeft + root.clientWidth < root.scrollWidth - 2;
  return left && right ? "both" : left ? "left" : right ? "right" : null;
}
