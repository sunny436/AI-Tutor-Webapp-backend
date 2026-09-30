"use client";

import { Button } from "@v1/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type PdfJs = typeof import("pdfjs-dist/legacy/build/pdf.mjs");
type PdfDocument = Awaited<ReturnType<PdfJs["getDocument"]>["promise"]>;

/**
 * One page of a PDF at the width of the reply, drawn by pdf.js (the legacy build: the widest
 * browser support). Its worker and the image decoders are plain files under /pdfjs/<version>/
 * (scripts/copy-pdfjs.mjs): same origin, no WebAssembly (the page's CSP forbids it), no eval.
 */
export default function PdfPreview({ url, page: first, onMissing }: { url: string; page: number; onMissing: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [doc, setDoc] = useState<PdfDocument | null>(null);
  const [page, setPage] = useState(Math.max(1, first));
  const [width, setWidth] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let loading: ReturnType<PdfJs["getDocument"]> | null = null;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
        const base = `/pdfjs/${pdfjs.version}`;
        pdfjs.GlobalWorkerOptions.workerSrc = `${base}/pdf.worker.min.mjs`;
        loading = pdfjs.getDocument({ url, useWasm: false, wasmUrl: `${base}/wasm/`, verbosity: 0 });
        const loaded = await loading.promise;
        if (cancelled) return;
        setPage((current) => Math.min(current, loaded.numPages));
        setDoc(loaded);
      } catch (error) {
        if (cancelled) return;
        if ((error as { status?: number })?.status === 404) onMissing();
        else setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      // Ends the document and its worker, loaded or still loading.
      void loading?.destroy();
    };
  }, [url, onMissing]);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry?.contentRect.width ?? 0)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!doc || !width) return;
    let cancelled = false;
    let task: { cancel(): void; promise: Promise<unknown> } | null = null;
    (async () => {
      try {
        const current = await doc.getPage(page);
        const target = canvas.current;
        if (cancelled || !target) return;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        const scale = width / current.getViewport({ scale: 1 }).width;
        const viewport = current.getViewport({ scale: scale * ratio });
        target.width = Math.floor(viewport.width);
        target.height = Math.floor(viewport.height);
        target.style.width = `${Math.floor(viewport.width / ratio)}px`;
        target.style.height = `${Math.floor(viewport.height / ratio)}px`;
        task = current.render({ canvas: target, viewport });
        await task.promise;
      } catch (error) {
        if (!cancelled && (error as { name?: string })?.name !== "RenderingCancelledException") setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page, width]);

  if (failed) {
    return <p className="text-sm text-text-secondary">This PDF can't be previewed here: download it to open it.</p>;
  }
  const pages = doc?.numPages ?? 0;
  return (
    <div className="min-w-0">
      <div
        ref={box}
        role="img"
        aria-label={pages ? `Page ${page} of ${pages}` : "Loading the PDF"}
        className="w-full min-w-0 overflow-hidden rounded-lg border border-border bg-card"
      >
        <canvas ref={canvas} className="block" />
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center justify-between gap-2 text-sm">
          <Button type="button" variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            <ChevronLeft aria-hidden className="mr-1 h-4 w-4" />
            Previous
          </Button>
          <span aria-live="polite" className="text-text-secondary">
            Page {page} of {pages}
          </span>
          <Button type="button" variant="outline" size="sm" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages}>
            Next
            <ChevronRight aria-hidden className="ml-1 h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
