"use client";

import { Button } from "@v1/ui/button";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LineChart,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  absDependencies,
  acosDependencies,
  addDependencies,
  asinDependencies,
  atanDependencies,
  cbrtDependencies,
  ceilDependencies,
  cosDependencies,
  coshDependencies,
  cotDependencies,
  create,
  cscDependencies,
  divideDependencies,
  expDependencies,
  floorDependencies,
  log10Dependencies,
  log2Dependencies,
  logDependencies,
  modDependencies,
  multiplyDependencies,
  parseDependencies,
  powDependencies,
  roundDependencies,
  secDependencies,
  signDependencies,
  sinDependencies,
  sinhDependencies,
  sqrtDependencies,
  subtractDependencies,
  tanDependencies,
  tanhDependencies,
  unaryMinusDependencies,
  unaryPlusDependencies,
} from "mathjs";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";

import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { parseJson, prefersReducedMotion, series, token } from "./tokens";

// Only what a school graph needs; mathjs evaluates in its own sandbox (no JavaScript).
const math = create(
  {
    parseDependencies: parseDependencies!,
    addDependencies: addDependencies!,
    subtractDependencies: subtractDependencies!,
    multiplyDependencies: multiplyDependencies!,
    divideDependencies: divideDependencies!,
    powDependencies: powDependencies!,
    unaryMinusDependencies: unaryMinusDependencies!,
    unaryPlusDependencies: unaryPlusDependencies!,
    modDependencies: modDependencies!,
    sinDependencies: sinDependencies!,
    cosDependencies: cosDependencies!,
    tanDependencies: tanDependencies!,
    secDependencies: secDependencies!,
    cscDependencies: cscDependencies!,
    cotDependencies: cotDependencies!,
    asinDependencies: asinDependencies!,
    acosDependencies: acosDependencies!,
    atanDependencies: atanDependencies!,
    sinhDependencies: sinhDependencies!,
    coshDependencies: coshDependencies!,
    tanhDependencies: tanhDependencies!,
    sqrtDependencies: sqrtDependencies!,
    cbrtDependencies: cbrtDependencies!,
    expDependencies: expDependencies!,
    logDependencies: logDependencies!,
    log10Dependencies: log10Dependencies!,
    log2Dependencies: log2Dependencies!,
    absDependencies: absDependencies!,
    floorDependencies: floorDependencies!,
    ceilDependencies: ceilDependencies!,
    roundDependencies: roundDependencies!,
    signDependencies: signDependencies!,
  },
  { predictable: true },
);

const FUNCTIONS = new Set([
  "sin",
  "cos",
  "tan",
  "sec",
  "csc",
  "cot",
  "asin",
  "acos",
  "atan",
  "sinh",
  "cosh",
  "tanh",
  "sqrt",
  "cbrt",
  "exp",
  "log",
  "log10",
  "log2",
  "abs",
  "floor",
  "ceil",
  "round",
  "sign",
  "mod",
]);
const OPERATORS = new Set(["add", "subtract", "multiply", "divide", "pow", "unaryMinus", "unaryPlus", "mod"]);
const SYMBOLS = new Set(["x", "pi", "e"]);
const SAMPLES = 400;

type AnyNode = { type: string; name?: string; fn?: unknown; value?: unknown; traverse(visit: (node: AnyNode) => void): void };

/** Numbers, x, pi, e, arithmetic and the functions above: anything else (assignments, objects,
 * matrices, strings, property access, unknown names) is refused before anything is evaluated. */
export function isSafeExpression(node: AnyNode): boolean {
  let safe = true;
  node.traverse((part) => {
    if (part.type === "ConstantNode") safe &&= typeof part.value === "number";
    else if (part.type === "SymbolNode") safe &&= SYMBOLS.has(part.name ?? "") || FUNCTIONS.has(part.name ?? "");
    else if (part.type === "OperatorNode") safe &&= OPERATORS.has(String(part.fn));
    else if (part.type === "FunctionNode") safe &&= FUNCTIONS.has((part.fn as { name?: string })?.name ?? "");
    else if (part.type !== "ParenthesisNode") safe = false;
  });
  return safe;
}

/** "y = x^2 - 2x" or "f(x) = …" or "x^2 - 2x" → a function of x, or null when it is not allowed. */
export function compileExpression(expression: string): ((x: number) => number) | null {
  const body = expression.replace(/^\s*(?:y|f\s*\(\s*x\s*\))\s*=\s*/i, "");
  try {
    const node = math.parse(body) as unknown as AnyNode & { compile(): { evaluate(scope: object): unknown } };
    if (!isSafeExpression(node)) return null;
    const code = node.compile();
    return (x) => {
      try {
        const y = code.evaluate({ x, pi: Math.PI, e: Math.E });
        return typeof y === "number" && Number.isFinite(y) ? y : Number.NaN;
      } catch {
        return Number.NaN;
      }
    };
  } catch {
    return null;
  }
}

const Num = z.number().finite();
const Spec = z.object({
  title: z.string().max(200).optional(),
  functions: z
    .array(z.object({ expr: z.string().min(1).max(200), label: z.string().max(80).optional() }))
    .min(1)
    .max(4),
  x: z.tuple([Num, Num]).optional(),
  y: z.tuple([Num, Num]).optional(),
  points: z.array(z.object({ x: Num, y: Num, label: z.string().max(40).optional() })).max(20).optional(),
});

type Range = [number, number];
type Plot = { label: string; fn: (x: number) => number };

function sample(fn: (x: number) => number, [from, to]: Range): { x: number; y: number }[] {
  return Array.from({ length: SAMPLES + 1 }, (_, index) => {
    const x = from + ((to - from) * index) / SAMPLES;
    return { x, y: fn(x) };
  });
}

/** A y-range that shows the curves, not their asymptotes: the middle 96% of the values, padded. */
function autoRange(values: number[]): Range {
  const finite = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!finite.length) return [-10, 10];
  const low = finite[Math.floor(finite.length * 0.02)] ?? -10;
  const high = finite[Math.ceil(finite.length * 0.98) - 1] ?? 10;
  if (high - low < 1e-9) return [low - 1, high + 1];
  const pad = (high - low) * 0.1;
  return [low - pad, high + pad];
}

/** Points to draw: gaps (null) where the curve is undefined or jumps (tan x at π/2), none outside. */
function line(points: { x: number; y: number }[], [low, high]: Range) {
  const span = high - low;
  return points.map((point, index) => {
    const previous = points[index - 1];
    const jump = previous && Number.isFinite(previous.y) && Math.abs(point.y - previous.y) > span;
    const far = point.y < low - 4 * span || point.y > high + 4 * span;
    return { x: point.x, y: !Number.isFinite(point.y) || jump || far ? null : point.y };
  });
}

const fmt = (value: number) => (Math.abs(value) >= 1000 || (value !== 0 && Math.abs(value) < 0.01) ? value.toExponential(2) : value.toFixed(2));

/**
 * ```graph: functions of x plotted by Chart.js from expressions mathjs parses and evaluates (an
 * allowlist of numbers, x, arithmetic and named functions, nothing else). Hover reads values;
 * zoom and pan redraw the curves at the new scale; a mouse can drag to pan.
 */
export default function MathGraph({ source, onError }: WidgetProps) {
  const spec = useMemo(() => {
    const parsed = Spec.safeParse(parseJson(source));
    if (!parsed.success) return null;
    const plots: Plot[] = [];
    for (const [index, item] of parsed.data.functions.entries()) {
      const fn = compileExpression(item.expr);
      if (!fn) return null;
      plots.push({ label: item.label ?? (parsed.data.functions.length > 1 ? `f${index + 1}(x) = ${item.expr}` : `y = ${item.expr}`), fn });
    }
    const [a, b] = parsed.data.x ?? [-10, 10];
    return a < b ? { ...parsed.data, plots, x: [a, b] as Range } : null;
  }, [source]);
  const [xRange, setXRange] = useState<Range | null>(null);
  const [yRange, setYRange] = useState<Range | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ at: number; range: Range } | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!spec) onError();
  }, [spec, onError]);

  const x = useMemo<Range>(() => xRange ?? spec?.x ?? [-10, 10], [xRange, spec]);
  const curves = useMemo(() => (spec ? spec.plots.map((plot) => sample(plot.fn, x)) : []), [spec, x]);
  const y = useMemo<Range>(
    () => yRange ?? spec?.y ?? autoRange(curves.flatMap((points) => points.map((point) => point.y))),
    [yRange, spec, curves],
  );

  useEffect(() => {
    if (!spec) return;
    let cancelled = false;
    let chart: { destroy(): void } | null = null;
    (async () => {
      try {
        const { default: Chart } = await import("chart.js/auto");
        const target = canvas.current;
        if (cancelled || !target) return;
        const palette = series();
        const ink = token("text-secondary");
        const grid = token("border");
        const axis = (range: Range) => ({ type: "linear", min: range[0], max: range[1], grid: { color: grid }, ticks: { color: ink }, border: { color: ink } });
        chart = new Chart(target, {
          type: "scatter",
          data: {
            datasets: [
              ...spec.plots.map((plot, index) => ({
                label: plot.label,
                data: line(curves[index] ?? [], y),
                showLine: true,
                pointRadius: 0,
                pointHitRadius: 6,
                borderWidth: 2,
                borderColor: palette[index],
                backgroundColor: palette[index],
                spanGaps: false,
              })),
              ...(spec.points?.length
                ? [{ label: "Points", data: spec.points, pointRadius: 5, backgroundColor: token("foreground"), showLine: false }]
                : []),
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: prefersReducedMotion() ? false : { duration: 0 },
            interaction: { mode: "nearest", intersect: false, axis: "x" },
            plugins: {
              legend: { position: "bottom", labels: { color: ink, boxWidth: 12, boxHeight: 12 } },
              tooltip: {
                callbacks: {
                  label: (item: { dataset: { label?: string }; parsed: { x: number; y: number }; dataIndex: number }) => {
                    const point = spec.points?.[item.dataIndex];
                    const name = item.dataset.label === "Points" && point?.label ? point.label : item.dataset.label;
                    return `${name}: (${fmt(item.parsed.x)}, ${fmt(item.parsed.y)})`;
                  },
                },
              },
            },
            scales: { x: axis(x), y: axis(y) },
          },
        } as never);
      } catch {
        if (!cancelled) onError();
      }
    })();
    return () => {
      cancelled = true;
      chart?.destroy();
    };
  }, [spec, curves, x, y, resolvedTheme, onError]);

  if (!spec) return null;
  const zoom = (factor: number) => {
    const [a, b] = x;
    const [c, d] = y;
    const mx = (a + b) / 2;
    const my = (c + d) / 2;
    setXRange([mx - ((b - a) * factor) / 2, mx + ((b - a) * factor) / 2]);
    setYRange([my - ((d - c) * factor) / 2, my + ((d - c) * factor) / 2]);
  };
  const pan = (dx: number, dy: number) => {
    setXRange([x[0] + (x[1] - x[0]) * dx, x[1] + (x[1] - x[0]) * dx]);
    setYRange([y[0] + (y[1] - y[0]) * dy, y[1] + (y[1] - y[0]) * dy]);
  };
  const control = "h-9 w-9 px-0";

  return (
    <CardFrame kind="graph" icon={LineChart} label="Graph" title={spec.title}>
      <div
        role="img"
        aria-label={`Graph of ${spec.plots.map((plot) => plot.label).join(", ")}, x from ${fmt(x[0])} to ${fmt(x[1])}`}
        className="relative h-64 w-full min-w-0 touch-pan-y rounded-lg border border-border bg-card sm:h-80"
        onPointerDown={(event) => {
          if (event.pointerType === "mouse") drag.current = { at: event.clientX, range: x };
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          const width = event.currentTarget.clientWidth || 1;
          if (!start) return;
          const shift = ((start.at - event.clientX) / width) * (start.range[1] - start.range[0]);
          setXRange([start.range[0] + shift, start.range[1] + shift]);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerLeave={() => {
          drag.current = null;
        }}
      >
        <canvas ref={canvas} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Graph controls">
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => zoom(0.5)} aria-label="Zoom in">
          <ZoomIn aria-hidden className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => zoom(2)} aria-label="Zoom out">
          <ZoomOut aria-hidden className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => pan(-0.25, 0)} aria-label="Move left">
          <ChevronLeft aria-hidden className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => pan(0.25, 0)} aria-label="Move right">
          <ChevronRight aria-hidden className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => pan(0, 0.25)} aria-label="Move up">
          <ChevronUp aria-hidden className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" className={control} onClick={() => pan(0, -0.25)} aria-label="Move down">
          <ChevronDown aria-hidden className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setXRange(null);
            setYRange(null);
          }}
        >
          <RotateCcw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
          Reset
        </Button>
      </div>
    </CardFrame>
  );
}
