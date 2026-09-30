"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@v1/ui/table";
import { Table2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";

import type { WidgetProps } from "../rich-block";
import { parseJson, prefersReducedMotion, series, token } from "./tokens";

const Num = z.number().finite();
const Point = z.object({ x: Num, y: Num });
const Spec = z.object({
  type: z.enum(["bar", "line", "area", "pie", "doughnut", "scatter", "radar"]),
  title: z.string().max(200).optional(),
  labels: z.array(z.union([z.string().max(80), Num])).max(500).optional(),
  datasets: z
    .array(
      z.object({
        label: z.string().max(80).optional(),
        data: z.array(z.union([Num, z.null(), Point])).max(2000),
      }),
    )
    .min(1)
    .max(12),
  xLabel: z.string().max(80).optional(),
  yLabel: z.string().max(80).optional(),
  stacked: z.boolean().optional(),
  horizontal: z.boolean().optional(),
});
export type ChartSpec = z.infer<typeof Spec>;

/** Series one chart draws; more than this and the data is shown as a table instead. */
const MAX_SERIES = 6;

/** The model's JSON, also in Chart.js's own shape ({type, data: {labels, datasets}}); null if unusable. */
export function readChart(source: string): ChartSpec | null {
  const raw = parseJson(source);
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const data = (value.data && typeof value.data === "object" ? value.data : {}) as Record<string, unknown>;
  const parsed = Spec.safeParse({ ...value, labels: value.labels ?? data.labels, datasets: value.datasets ?? data.datasets });
  return parsed.success ? parsed.data : null;
}

/** A pie of many slices keeps its five largest and folds the rest into "Other" (colours never repeat). */
export function foldSlices(spec: ChartSpec): ChartSpec {
  const round = spec.type === "pie" || spec.type === "doughnut";
  const values = spec.datasets[0]?.data ?? [];
  if (!round || values.length <= MAX_SERIES) return spec;
  const slices = values.map((value, index) => ({
    label: String(spec.labels?.[index] ?? `Part ${index + 1}`),
    value: typeof value === "number" ? value : 0,
  }));
  slices.sort((a, b) => b.value - a.value);
  const kept = slices.slice(0, MAX_SERIES - 1);
  const other = slices.slice(MAX_SERIES - 1).reduce((sum, slice) => sum + slice.value, 0);
  return {
    ...spec,
    labels: [...kept.map((slice) => slice.label), "Other"],
    datasets: [{ label: spec.datasets[0]?.label, data: [...kept.map((slice) => slice.value), other] }],
  };
}

function describe(spec: ChartSpec): string {
  const names = spec.datasets.map((set, index) => set.label ?? `series ${index + 1}`).join(", ");
  return `${spec.title ?? "Chart"}: a ${spec.type} chart of ${names}. The data table has every value.`;
}

function config(spec: ChartSpec, font: string) {
  const palette = series();
  const ink = token("text-secondary");
  const grid = token("border");
  const surface = token("card");
  const round = spec.type === "pie" || spec.type === "doughnut";
  const kind = spec.type === "area" ? "line" : spec.type;
  const axis = { grid: { color: grid }, ticks: { color: ink }, border: { color: grid } };
  return {
    type: kind,
    data: {
      labels: spec.labels,
      datasets: spec.datasets.map((set, index) => {
        const colour = palette[index % palette.length] ?? palette[0];
        if (round) {
          return {
            label: set.label,
            data: set.data,
            backgroundColor: set.data.map((_, slice) => palette[slice % palette.length]),
            borderColor: surface,
            borderWidth: 2,
          };
        }
        return {
          label: set.label ?? `Series ${index + 1}`,
          data: set.data,
          backgroundColor: kind === "bar" || kind === "scatter" ? colour : `${colour}33`,
          borderColor: colour,
          borderWidth: 2,
          borderRadius: kind === "bar" ? 4 : 0,
          pointRadius: kind === "scatter" ? 4 : 3,
          pointHoverRadius: 6,
          fill: spec.type === "area",
          tension: 0,
        };
      }),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: prefersReducedMotion() ? false : { duration: 300 },
      indexAxis: spec.horizontal && kind === "bar" ? "y" : "x",
      interaction: { mode: round || kind === "scatter" ? "nearest" : "index", intersect: round },
      font: { family: font },
      plugins: {
        legend: {
          display: round || spec.datasets.length > 1,
          position: "bottom",
          labels: { color: ink, boxWidth: 12, boxHeight: 12, font: { family: font } },
        },
        tooltip: { enabled: true },
      },
      scales: round
        ? {}
        : kind === "radar"
          ? { r: { grid: { color: grid }, angleLines: { color: grid }, pointLabels: { color: ink }, ticks: { color: ink, backdropColor: "transparent" } } }
          : {
              x: {
                ...axis,
                // Only a scatter's x is numeric; anything else keeps Chart.js's category axis (the labels).
                ...(kind === "scatter" ? { type: "linear" } : {}),
                stacked: Boolean(spec.stacked),
                title: { display: Boolean(spec.xLabel), text: spec.xLabel, color: ink },
              },
              y: {
                ...axis,
                stacked: Boolean(spec.stacked),
                beginAtZero: kind === "bar",
                title: { display: Boolean(spec.yLabel), text: spec.yLabel, color: ink },
              },
            },
    },
  };
}

function DataTable({ spec }: { spec: ChartSpec }) {
  const rows = Math.max(spec.labels?.length ?? 0, ...spec.datasets.map((set) => set.data.length));
  const cell = (value: unknown) =>
    value === null || value === undefined ? "–" : typeof value === "object" ? `(${(value as { x: number }).x}, ${(value as { y: number }).y})` : String(value);
  return (
    <div className="mt-3">
      <Table label={`${spec.title ?? "Chart"} data`} className="min-w-full text-sm">
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-nowrap">{spec.xLabel ?? ""}</TableHead>
            {spec.datasets.map((set, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: series have no id but their place
              <TableHead key={index} className="whitespace-nowrap">
                {set.label ?? `Series ${index + 1}`}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rows }, (_, row) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions in the data
            <TableRow key={row}>
              <TableCell className="whitespace-nowrap font-medium">{String(spec.labels?.[row] ?? row + 1)}</TableCell>
              {spec.datasets.map((set, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: series have no id but their place
                <TableCell key={index}>{cell(set.data[row])}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * A ```chart block drawn by Chart.js: the design system's validated series colours, the app's
 * ink and gridlines, a legend for two or more series, tooltips, and the numbers as a table for
 * anyone who cannot read the picture. Drawn again when the theme changes.
 */
export default function ChartView({ source, onError }: WidgetProps) {
  const spec = useMemo(() => {
    const read = readChart(source);
    return read ? foldSlices(read) : null;
  }, [source]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [table, setTable] = useState(false);
  const { resolvedTheme } = useTheme();
  const drawable = spec !== null && spec.datasets.length <= MAX_SERIES;

  useEffect(() => {
    if (!spec) onError();
  }, [spec, onError]);

  useEffect(() => {
    if (!spec || !drawable) return;
    let cancelled = false;
    let chart: { destroy(): void } | null = null;
    (async () => {
      try {
        const { default: Chart } = await import("chart.js/auto");
        const target = canvas.current;
        if (cancelled || !target) return;
        const font = getComputedStyle(target).fontFamily;
        chart = new Chart(target, config(spec, font) as never);
      } catch {
        if (!cancelled) onError();
      }
    })();
    return () => {
      cancelled = true;
      chart?.destroy();
    };
  }, [spec, drawable, resolvedTheme, onError]);

  if (!spec) return null;
  return (
    <figure className="my-3 min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
      {spec.title ? <figcaption className="mb-2 text-sm font-semibold text-foreground">{spec.title}</figcaption> : null}
      {drawable ? (
        <div role="img" aria-label={describe(spec)} className="relative h-64 w-full min-w-0 sm:h-80">
          <canvas ref={canvas} />
        </div>
      ) : (
        <p className="text-sm text-text-secondary">Too many series to draw clearly, so here is the data.</p>
      )}
      {drawable ? (
        <button
          type="button"
          onClick={() => setTable((shown) => !shown)}
          aria-expanded={table}
          className="focus-ring mt-2 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-2 hover:text-foreground"
        >
          <Table2 aria-hidden className="h-3.5 w-3.5" />
          {table ? "Hide the data table" : "Show the data table"}
        </button>
      ) : null}
      {table || !drawable ? <DataTable spec={spec} /> : null}
    </figure>
  );
}
