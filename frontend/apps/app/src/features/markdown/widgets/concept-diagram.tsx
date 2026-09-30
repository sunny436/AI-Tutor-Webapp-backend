"use client";

import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Background, Controls, type Edge, MarkerType, type Node, Position, ReactFlow } from "@xyflow/react";
import { Network } from "lucide-react";
import { useTheme } from "next-themes";
import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import { z } from "zod";

import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { parseJson } from "./tokens";

const Spec = z.object({
  title: z.string().max(200).optional(),
  direction: z.enum(["TB", "LR", "BT", "RL"]).optional(),
  nodes: z
    .array(z.object({ id: z.string().min(1).max(40), label: z.string().min(1).max(80), detail: z.string().max(600).optional() }))
    .min(1)
    .max(40),
  edges: z
    .array(z.object({ from: z.string().min(1).max(40), to: z.string().min(1).max(40), label: z.string().max(40).optional() }))
    .max(80)
    .optional(),
});
type DiagramSpec = z.infer<typeof Spec>;

const WIDTH = 150;

/** React Flow's own colours, from the design system (light, dark and high contrast alike). Set on
 * its root element: its themes define these same variables there, and an inline style wins. */
const THEME = {
  "--xy-node-background-color-default": "hsl(var(--card))",
  "--xy-node-border-default": "1px solid hsl(var(--border))",
  "--xy-node-color-default": "hsl(var(--foreground))",
  "--xy-node-boxshadow-selected-default": "0 0 0 2px hsl(var(--brand))",
  "--xy-edge-stroke-default": "hsl(var(--text-secondary))",
  "--xy-edge-label-background-color-default": "hsl(var(--card))",
  "--xy-edge-label-color-default": "hsl(var(--foreground))",
  "--xy-background-color-default": "hsl(var(--surface))",
  "--xy-background-pattern-dots-color-default": "hsl(var(--border))",
  "--xy-controls-button-background-color-default": "hsl(var(--card))",
  "--xy-controls-button-background-color-hover-default": "hsl(var(--surface-2))",
  "--xy-controls-button-color-default": "hsl(var(--foreground))",
  "--xy-controls-button-border-color-default": "hsl(var(--border))",
} as CSSProperties;

/** Boxes placed in layers by dagre, arrows between them. */
function layout(spec: DiagramSpec): { nodes: Node[]; edges: Edge[] } {
  const direction = spec.direction ?? "TB";
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: direction, nodesep: 18, ranksep: 48, marginx: 8, marginy: 8 });
  graph.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(spec.nodes.map((node) => node.id));
  const height = (label: string) => Math.min(96, 44 + 18 * Math.floor(label.length / 22));
  for (const node of spec.nodes) graph.setNode(node.id, { width: WIDTH, height: height(node.label) });
  const edges = (spec.edges ?? []).filter((edge) => ids.has(edge.from) && ids.has(edge.to));
  for (const edge of edges) graph.setEdge(edge.from, edge.to);
  dagre.layout(graph);
  const across = direction === "LR" || direction === "RL";
  return {
    nodes: spec.nodes.map((node) => {
      const place = graph.node(node.id) as { x: number; y: number };
      const tall = height(node.label);
      return {
        id: node.id,
        position: { x: place.x - WIDTH / 2, y: place.y - tall / 2 },
        data: { label: node.label },
        style: { width: WIDTH, fontSize: 13, lineHeight: 1.35 },
        sourcePosition: across ? Position.Right : Position.Bottom,
        targetPosition: across ? Position.Left : Position.Top,
        connectable: false,
      };
    }),
    edges: edges.map((edge, index) => ({
      id: `e${index}`,
      source: edge.from,
      target: edge.to,
      label: edge.label,
      markerEnd: { type: MarkerType.ArrowClosed },
    })),
  };
}

/**
 * ```diagram: a concept map to explore. Boxes are laid out by dagre and drawn by React Flow;
 * choosing one (click, or focus and Enter) shows its detail below. On touch screens the diagram
 * never captures the page's scroll: it zooms with its buttons, and the text version is below.
 */
export default function ConceptDiagram({ source, onError }: WidgetProps) {
  const spec = useMemo(() => {
    const parsed = Spec.safeParse(parseJson(source));
    return parsed.success ? parsed.data : null;
  }, [source]);
  const flow = useMemo(() => (spec ? layout(spec) : null), [spec]);
  const [selected, setSelected] = useState<string | null>(null);
  const [fine, setFine] = useState(false);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!spec) onError();
  }, [spec, onError]);
  useEffect(() => setFine(window.matchMedia("(pointer: fine)").matches), []);
  const onSelectionChange = useCallback(({ nodes }: { nodes: Node[] }) => setSelected(nodes[0]?.id ?? null), []);

  if (!spec || !flow) return null;
  const chosen = spec.nodes.find((node) => node.id === selected);
  const label = (id: string) => spec.nodes.find((node) => node.id === id)?.label ?? id;

  return (
    <CardFrame kind="diagram" icon={Network} label="Diagram" title={spec.title}>
      <div className="h-80 w-full min-w-0 overflow-hidden rounded-lg border border-border sm:h-96">
        <ReactFlow
          defaultNodes={flow.nodes}
          defaultEdges={flow.edges}
          style={THEME}
          fitView
          fitViewOptions={{ padding: 0.12, maxZoom: 1.25 }}
          minZoom={0.2}
          maxZoom={2}
          nodesDraggable={fine}
          nodesConnectable={false}
          elementsSelectable
          panOnDrag={fine}
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
          onSelectionChange={onSelectionChange}
          onNodeClick={(_, node) => setSelected(node.id)}
          colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        >
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div aria-live="polite" className="mt-2 min-h-6 text-sm leading-6">
        {chosen ? (
          <p>
            <span className="font-semibold">{chosen.label}</span>
            {chosen.detail ? <span className="text-text-secondary">: {chosen.detail}</span> : null}
          </p>
        ) : spec.nodes.some((node) => node.detail) ? (
          <p className="text-text-secondary">Choose a box to read more about it.</p>
        ) : null}
      </div>
      <details className="mt-1 text-sm">
        <summary className="focus-ring w-fit cursor-pointer rounded-md text-text-secondary hover:text-foreground">
          The diagram as text
        </summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 leading-6">
          {spec.nodes.map((node) => (
            <li key={node.id}>
              <span className="font-medium">{node.label}</span>
              {node.detail ? `: ${node.detail}` : ""}
              {(spec.edges ?? [])
                .filter((edge) => edge.from === node.id)
                .map((edge) => ` → ${label(edge.to)}${edge.label ? ` (${edge.label})` : ""}`)
                .join("")}
            </li>
          ))}
        </ul>
      </details>
    </CardFrame>
  );
}
