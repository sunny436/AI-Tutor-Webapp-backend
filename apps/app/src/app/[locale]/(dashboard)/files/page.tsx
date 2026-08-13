"use client";

/**
 * Files page — premium redesign (Google Drive-style).
 * Upload/delete/pagination logic is UNCHANGED (Convex file storage).
 */

import { ConfirmButton } from "@/components/confirm-button";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { useMutation, usePaginatedQuery } from "convex/react";
import {
  FileText, HardDrive, ImageIcon, Search, Trash2, Upload, UploadCloud,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function iconFor(type: string) {
  if (type?.startsWith("image/")) return { Icon: ImageIcon, tint: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400" };
  if (type?.includes("pdf")) return { Icon: FileText, tint: "bg-rose-500/12 text-rose-600 dark:text-rose-400" };
  return { Icon: FileText, tint: "bg-sky-500/12 text-sky-600 dark:text-sky-400" };
}

export default function FilesPage() {
  const { current } = useWorkspace();
  const { results: files, status, loadMore } = usePaginatedQuery(
    api.files.listPaged,
    current ? { workspaceId: current } : "skip",
    { initialNumItems: 24 },
  );
  const generateUploadUrl = useMutation(api.files.generateUploadUrl);
  const saveFile = useMutation(api.files.saveFile);
  const removeFile = useMutation(api.files.remove);
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [search, setSearch] = useState("");

  const uploadFile = async (file: File) => {
    if (!file || !current) return;
    setBusy(true);
    try {
      const url = await generateUploadUrl({ workspaceId: current });
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": file.type || "application/octet-stream" },
        body: file,
      });
      const { storageId } = await res.json();
      await saveFile({
        workspaceId: current,
        storageId,
        name: file.name,
        size: file.size,
        contentType: file.type || "application/octet-stream",
      });
      if (inputRef.current) inputRef.current.value = "";
      toast.success(`Uploaded ${file.name}`);
    } catch {
      toast.error("Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const onInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) uploadFile(f);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) uploadFile(f);
  };

  const usedBytes = useMemo(() => files.reduce((n, f) => n + (f.size ?? 0), 0), [files]);
  const filtered = files.filter((f) => f.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="min-h-[calc(100vh-3rem)] w-full bg-gradient-to-br from-emerald-50 via-white to-teal-50 px-6 py-7 dark:from-zinc-950 dark:via-black dark:to-emerald-950/30">
      <div className="mx-auto w-full max-w-screen-xl space-y-5">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-primary">Files</h1>
            <p className="mt-0.5 text-sm text-primary/60">Your reports & documents, stored securely.</p>
          </div>
          <label className="cursor-pointer">
            <input ref={inputRef} type="file" className="hidden" disabled={busy || !current} onChange={onInput} />
            <span className={`inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/25 transition hover:brightness-105 ${busy ? "opacity-60" : ""}`}>
              <Upload className="h-4 w-4" /> {busy ? "Uploading…" : "Upload"}
            </span>
          </label>
        </div>

        {/* Dropzone + storage */}
        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition ${
              drag ? "border-emerald-500 bg-emerald-500/10" : "border-emerald-500/30 bg-emerald-500/[0.04] hover:bg-emerald-500/[0.07]"
            }`}
          >
            <span className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-lg shadow-emerald-500/25">
              <UploadCloud className="h-7 w-7" />
            </span>
            <p className="text-sm font-semibold text-primary">Drag &amp; drop files here</p>
            <p className="mt-1 text-xs text-primary/50">or click to browse · PDF, PNG, JPG</p>
          </button>

          <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-primary">
              <HardDrive className="h-4 w-4 text-primary/50" /> Storage
            </div>
            <p className="text-2xl font-bold text-primary">{fmtSize(usedBytes)}</p>
            <p className="mt-0.5 text-xs text-primary/50">{files.length} file{files.length === 1 ? "" : "s"} in this workspace</p>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-primary/5">
              <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500" style={{ width: `${Math.min(100, (usedBytes / (200 * 1024 * 1024)) * 100)}%` }} />
            </div>
          </div>
        </div>

        {/* Search */}
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-primary/30" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search files…"
            className="w-full rounded-xl border border-border bg-card py-2 pl-9 pr-3 text-sm outline-none focus:border-emerald-500/50" />
        </div>

        {/* Grid */}
        {status === "LoadingFirstPage" ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length placeholder list, never reordered and holding no state
              <div key={i} className="h-28 animate-pulse rounded-2xl border border-border bg-card" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-16 text-center">
            <span className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"><UploadCloud className="h-7 w-7" /></span>
            <p className="text-sm font-medium text-primary">No files yet</p>
            <p className="text-xs text-primary/50">Drag a report above to get started.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
            {filtered.map((f) => {
              const { Icon, tint } = iconFor(f.contentType);
              return (
                <div key={f._id} className="group relative rounded-2xl border border-border bg-card p-4 shadow-sm transition hover:-translate-y-1 hover:border-emerald-500/30 hover:shadow-lg">
                  <span className={`mb-3 grid h-11 w-11 place-items-center rounded-xl ${tint}`}><Icon className="h-5 w-5" /></span>
                  {f.url ? (
                    <a href={f.url} target="_blank" rel="noreferrer" className="block truncate text-sm font-semibold text-primary hover:text-emerald-600 dark:hover:text-emerald-400">{f.name}</a>
                  ) : (
                    <span className="block truncate text-sm font-semibold text-primary">{f.name}</span>
                  )}
                  <p className="mt-0.5 text-[11px] text-primary/50">{fmtSize(f.size)} · {new Date(f.createdAt).toLocaleDateString()}</p>
                  <div className="absolute right-2 top-2 opacity-0 transition group-hover:opacity-100">
                    <ConfirmButton
                      label={<Trash2 className="h-3.5 w-3.5" />}
                      className="grid h-7 w-7 place-items-center rounded-lg border border-border bg-card text-rose-500 shadow-sm transition hover:bg-rose-500/10"
                      title="Delete file?"
                      description={f.name}
                      confirmLabel="Delete"
                      onConfirm={async () => { await removeFile({ fileId: f._id }); toast.success("File deleted"); }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {status === "CanLoadMore" && (
          <div className="flex justify-center">
            <Button variant="outline" size="sm" onClick={() => loadMore(24)}>Load more</Button>
          </div>
        )}
        {status === "LoadingMore" && <p className="text-center text-sm text-primary/40">Loading…</p>}
      </div>
    </div>
  );
}
