"use client";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@v1/ui/dialog";
import { Code2, Maximize2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useId, useState } from "react";

import type { WidgetProps } from "../rich-block";
import { token } from "./tokens";

// A font every device has, so the boxes mermaid measures in the page fit the text in the image.
const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif';

type Drawn = { url: string; width: number; height: number };

/** mermaid's SVG with a fixed size (it says width="100%"), as an image URL. */
function asImage(svg: string): Drawn {
  const box = /viewBox="[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)"/.exec(svg);
  const width = Math.ceil(Number(box?.[1] ?? 600));
  const height = Math.ceil(Number(box?.[2] ?? 400));
  const sized = svg.replace(/<svg\b[^>]*>/, (open) =>
    open
      .replace(/\swidth="[^"]*"/, "")
      .replace(/\sheight="[^"]*"/, "")
      .replace(/\sstyle="[^"]*"/, "")
      .replace(/^<svg/, `<svg width="${width}" height="${height}"`),
  );
  return { url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(sized)}`, width, height };
}

/**
 * A ```mermaid block drawn as a diagram. mermaid runs in strict mode (no scripts, no clicks, its
 * own sanitiser) with the dagre layout (the ELK engine is never loaded), in the design system's
 * colours. The finished SVG is shown as an IMAGE: nothing inside an image can run or fetch.
 */
export default function MermaidDiagram({ source, onError }: WidgetProps) {
  const { resolvedTheme } = useTheme();
  const id = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const [open, setOpen] = useState(false);
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          layout: "dagre",
          htmlLabels: false,
          suppressErrorRendering: true,
          maxTextSize: 20_000,
          maxEdges: 300,
          fontFamily: FONT,
          theme: "base",
          themeVariables: {
            darkMode: resolvedTheme === "dark",
            fontFamily: FONT,
            fontSize: "14px",
            background: token("card"),
            primaryColor: token("study-card-background"),
            primaryTextColor: token("foreground"),
            primaryBorderColor: token("brand"),
            secondaryColor: token("surface-2"),
            tertiaryColor: token("brand-soft"),
            lineColor: token("text-secondary"),
            textColor: token("foreground"),
            mainBkg: token("study-card-background"),
            nodeBorder: token("brand"),
            clusterBkg: token("surface"),
            clusterBorder: token("border"),
            edgeLabelBackground: token("card"),
            noteBkgColor: token("brand-soft"),
            noteTextColor: token("foreground"),
            noteBorderColor: token("border"),
            actorBkg: token("study-card-background"),
            actorBorder: token("brand"),
            actorTextColor: token("foreground"),
            signalColor: token("text-secondary"),
            signalTextColor: token("foreground"),
          },
        });
        if (!(await mermaid.parse(source, { suppressErrors: true }))) throw new Error("not mermaid");
        const { svg } = await mermaid.render(id, source);
        if (!cancelled) setDrawn(asImage(svg));
      } catch {
        if (!cancelled) onError();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, resolvedTheme, id, onError]);

  if (!drawn) {
    return (
      <div
        role="status"
        className="my-3 flex h-24 items-center justify-center rounded-xl border border-border bg-study-card text-sm text-text-secondary"
      >
        Drawing the diagram…
      </div>
    );
  }

  return (
    <figure className="my-3 min-w-0 rounded-xl border border-border bg-card">
      <div className="flex items-center justify-end gap-1 border-b border-border px-2 py-1 text-2xs text-text-secondary">
        <button
          type="button"
          onClick={() => setShowSource((shown) => !shown)}
          aria-expanded={showSource}
          className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-surface-2 hover:text-foreground"
        >
          <Code2 aria-hidden className="h-3.5 w-3.5" />
          Source
        </button>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-surface-2 hover:text-foreground"
        >
          <Maximize2 aria-hidden className="h-3.5 w-3.5" />
          Expand
        </button>
      </div>
      <div className="p-2 sm:p-3">
        <img
          src={drawn.url}
          width={drawn.width}
          height={drawn.height}
          alt="Diagram (its text is in Source)"
          className="mx-auto block h-auto max-w-full"
        />
      </div>
      {showSource && (
        <pre className="scrollbar-subtle max-h-64 overflow-auto border-t border-border p-3 font-mono text-xs leading-5 text-text-secondary">
          {source}
        </pre>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[min(96vw,80rem)] p-4 sm:p-6">
          <DialogTitle>Diagram</DialogTitle>
          <DialogDescription className="sr-only">The diagram at full size; scroll to see all of it.</DialogDescription>
          <div className="scrollbar-subtle max-h-[75dvh] overflow-auto rounded-lg border border-border bg-card p-2">
            <img src={drawn.url} width={drawn.width} height={drawn.height} alt="Diagram at full size" className="max-w-none" />
          </div>
        </DialogContent>
      </Dialog>
    </figure>
  );
}
