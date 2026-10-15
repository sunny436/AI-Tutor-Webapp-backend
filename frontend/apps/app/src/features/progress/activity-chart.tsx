"use client";

import { type CSSProperties, type KeyboardEvent, useId, useRef, useState } from "react";

/** A day's minutes; `questions` only where the chart shows them (Progress & Goals). */
export type ChartDay = { date: string; activeMinutes: number; questions?: number };

function dayLabel(iso: string, style: "short" | "long"): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year as number, (month as number) - 1, day as number));
  return date.toLocaleDateString(undefined, {
    timeZone: "UTC",
    weekday: style === "long" ? "long" : undefined,
    day: "numeric",
    month: "short",
  });
}

function minutes(value: number): string {
  return value === 1 ? "1 min" : `${value} min`;
}

/** A bar's height as a percentage of the plot; any activity at all stays visible. */
function barHeight(value: number, top: number): number {
  return value > 0 ? Math.max((value / top) * 100, 3) : 0;
}

/** Near either end the tooltip lines up with the outer edge of its bar, so it stays inside. */
function tooltipAnchor(index: number, count: number): "start" | "center" | "end" {
  if (index < count / 4) return "start";
  if (index >= count - count / 4) return "end";
  return "center";
}

function tooltipPosition(index: number, count: number): CSSProperties {
  const anchor = tooltipAnchor(index, count);
  if (anchor === "start") return { left: `${(index / count) * 100}%` };
  if (anchor === "end") return { right: `${((count - 1 - index) / count) * 100}%` };
  return { left: `${((index + 0.5) / count) * 100}%` };
}

function questions(count: number): string {
  return `${count} ${count === 1 ? "question" : "questions"}`;
}

/**
 * Minutes per day, as columns (active time in PadhAI, or estimated study time). One series, so no
 * legend: the title names it.
 * - Marks: at most 24px wide, 4px rounded at the top and square on the baseline, 2px apart.
 * - Hover or focus a day for its tooltip; the chart is one tab stop and the arrow keys move
 *   between days. Every value is also in the table below the chart ("Show as table").
 * - A daily goal, if set, is a dashed reference line.
 * Colours are tokens: the bars' brand colour measures 6.31:1 on a card in light, 6.02:1 in
 * dark; text never takes the bar colour.
 */
export function ActivityChart({
  days,
  goal,
  title = `Active minutes, last ${days.length} days`,
  valueLabel = "active",
  columnLabel = "Active time",
}: {
  days: ChartDay[];
  goal: number | null;
  title?: string;
  /** After each day's minutes in its spoken label: "12 min active". */
  valueLabel?: string;
  columnLabel?: string;
}) {
  const withQuestions = days.some((day) => day.questions !== undefined);
  const [active, setActive] = useState<number | null>(null);
  const [focused, setFocused] = useState(days.length - 1);
  const [table, setTable] = useState(false);
  const bars = useRef<(HTMLDivElement | null)[]>([]);
  const titleId = useId();
  const tableId = useId();
  const top = Math.max(goal ?? 0, ...days.map((day) => day.activeMinutes), 10);
  const shown = active !== null ? days[active] : null;

  const move = (event: KeyboardEvent<HTMLDivElement>, index: number) => {
    const next =
      event.key === "ArrowRight" ? index + 1 : event.key === "ArrowLeft" ? index - 1 : event.key === "Home" ? 0 : event.key === "End" ? days.length - 1 : null;
    if (next === null || next < 0 || next >= days.length) return;
    event.preventDefault();
    setFocused(next);
    setActive(next);
    bars.current[next]?.focus();
  };

  return (
    <figure className="flex flex-col gap-2">
      <figcaption id={titleId} className="text-sm font-bold text-foreground">
        {title}
      </figcaption>
      {/* The top padding is room for the tooltip over the tallest bar: it never covers the title. */}
      <div className="pt-8">
        <div className="flex items-end justify-between text-2xs text-text-secondary">
          <span>{minutes(top)}</span>
        </div>
        <div role="group" aria-labelledby={titleId} className="relative mt-1 flex h-32 items-end gap-0.5 border-b border-border">
          {goal ? (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-text-secondary/60"
              style={{ bottom: `${(goal / top) * 100}%` }}
            >
              <span className="absolute -top-4 right-0 bg-card px-1 text-2xs text-text-secondary">Goal {minutes(goal)}</span>
            </div>
          ) : null}
          {days.map((day, index) => (
            <div
              key={day.date}
              ref={(node) => {
                bars.current[index] = node;
              }}
              role="img"
              tabIndex={index === focused ? 0 : -1}
              aria-label={`${dayLabel(day.date, "long")}: ${minutes(day.activeMinutes)} ${valueLabel}${day.questions === undefined ? "" : `, ${questions(day.questions)}`}`}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive((current) => (current === index ? null : current))}
              onFocus={() => {
                setFocused(index);
                setActive(index);
              }}
              onBlur={() => setActive((current) => (current === index ? null : current))}
              onKeyDown={(event) => move(event, index)}
              className="focus-ring flex h-full min-w-0 flex-1 items-end justify-center rounded-sm"
            >
              {day.activeMinutes > 0 && (
                <div
                  className="w-full max-w-6 rounded-t bg-brand"
                  style={{ height: `${barHeight(day.activeMinutes, top)}%` }}
                />
              )}
            </div>
          ))}
          {shown && active !== null && (
            <div
              aria-hidden
              className={`pointer-events-none absolute z-10 whitespace-nowrap rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground elev-2 ${
                tooltipAnchor(active, days.length) === "center" ? "-translate-x-1/2" : ""
              }`}
              style={{ ...tooltipPosition(active, days.length), bottom: `calc(${barHeight(shown.activeMinutes, top)}% + 6px)` }}
            >
              <strong className="font-bold">{minutes(shown.activeMinutes)}</strong>{" "}
              <span className="text-text-secondary">
                {shown.questions === undefined ? "" : ` · ${questions(shown.questions)}`} · {dayLabel(shown.date, "short")}
              </span>
            </div>
          )}
        </div>
        <div className="mt-1 flex justify-between text-2xs text-text-secondary">
          <span>{days[0] ? dayLabel(days[0].date, "short") : ""}</span>
          <span>Today</span>
        </div>
      </div>
      <button
        type="button"
        aria-expanded={table}
        aria-controls={tableId}
        onClick={() => setTable((open) => !open)}
        className="focus-ring self-start rounded text-xs font-medium text-brand underline underline-offset-2"
      >
        {table ? "Hide table" : "Show as table"}
      </button>
      <div id={tableId} hidden={!table} className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="bg-surface text-xs text-text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">
                Day
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                {columnLabel}
              </th>
              {withQuestions && (
                <th scope="col" className="px-3 py-2 text-right font-semibold">
                  Questions
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {[...days].reverse().map((day) => (
              <tr key={day.date}>
                <th scope="row" className="px-3 py-1.5 font-normal text-foreground">
                  {dayLabel(day.date, "long")}
                </th>
                <td className="px-3 py-1.5 text-right tabular-nums text-foreground">{minutes(day.activeMinutes)}</td>
                {withQuestions && <td className="px-3 py-1.5 text-right tabular-nums text-foreground">{day.questions}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
