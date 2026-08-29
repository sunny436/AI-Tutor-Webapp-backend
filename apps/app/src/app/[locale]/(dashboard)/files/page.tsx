"use client";

/**
 * Reports — the documents a user keeps here.
 *
 * THE HONEST BIT, WHICH THE OLD PAGE HID
 *
 * This app has TWO upload systems that share nothing:
 *
 *   this page          -> Convex storage (`api.files.*`). Stored, listed,
 *                         downloadable. The assistant CANNOT read any of it.
 *   the chat's paperclip -> POST /upload on the Python backend, which extracts
 *                         the text and STORES NOTHING. The assistant can read
 *                         it only while the chat tab holds it in memory, and
 *                         it is never listed anywhere.
 *
 * The paperclip used to index into a private Chroma collection, so an uploaded
 * report survived a reload and carried into the next conversation. It no longer
 * does: the backend hands the text back and keeps none of it, the consult page
 * holds it in component state, and a refresh loses it. That widens the gap
 * between the two systems rather than closing it — this page persists but
 * cannot be read, the paperclip can be read but does not persist.
 *
 * The old copy here read "Your reports & documents, stored securely", which
 * invites exactly the wrong conclusion — that uploading a blood test here lets
 * you then ask about it. It does not. Somebody uploading a report and getting
 * "I can't see any report" back would reasonably think the product was broken.
 *
 * Unifying the two stores is a backend change and is not in this redesign. What
 * IS in scope is telling the truth: this page says what it holds, and points at
 * the chat for the thing people actually want.
 *
 * Upload, delete, search and pagination logic are unchanged.
 */

import { ConfirmButton } from "@/components/confirm-button";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@v1/backend/convex/_generated/api";
import { Button } from "@v1/ui/button";
import { Card } from "@v1/ui/card";
import { EmptyState } from "@v1/ui/empty-state";
import { PageShell } from "@v1/ui/page-shell";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { useMutation, usePaginatedQuery } from "convex/react";
import {
  FileText,
  FolderOpen,
  HardDrive,
  ImageIcon,
  MessageSquare,
  Search,
  Trash2,
  Upload,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function iconFor(type: string) {
  if (type?.startsWith("image/")) return ImageIcon;
  return FileText;
}

export default function FilesPage() {
  const { current } = useWorkspace();
  const {
    results: files,
    status,
    loadMore,
  } = usePaginatedQuery(
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
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) uploadFile(f);
  };

  const usedBytes = useMemo(() => files.reduce((n, f) => n + (f.size ?? 0), 0), [files]);
  const filtered = files.filter((f) =>
    f.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <PageShell>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            Reports
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            Documents you keep on file — stored, listed and downloadable.
          </p>
        </div>
        <label className="shrink-0 cursor-pointer">
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            disabled={busy || !current}
            onChange={onInput}
          />
          <span
            className={`inline-flex h-11 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-medium text-brand-foreground elev-1 transition hover:brightness-110 sm:h-10 ${
              busy ? "opacity-60" : ""
            }`}
          >
            <Upload aria-hidden className="h-4 w-4" /> {busy ? "Uploading…" : "Upload"}
          </span>
        </label>
      </div>

      {/* The correction. Prominent enough to be read before uploading, quiet
          enough not to be a warning — nothing is wrong, it just is not what
          people assume. */}
      <Card className="mb-4 flex flex-col gap-3 border-info/25 bg-info-soft/50 p-4 sm:flex-row sm:items-center">
        <span
          aria-hidden
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-info/15 text-info"
        >
          <MessageSquare className="h-[18px] w-[18px]" />
        </span>
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-text-secondary">
          <span className="font-medium text-foreground">
            The assistant can&apos;t read files stored here.
          </span>{" "}
          To ask about a report, attach it inside a consultation with the paperclip —
          that copy is read and can be discussed.
        </p>
        <Button asChild variant="outline" size="sm" className="shrink-0">
          <Link href="/consult">Open a consultation</Link>
        </Button>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
            drag
              ? "border-brand bg-brand-soft"
              : "border-border bg-surface-2/50 hover:border-brand/40 hover:bg-brand-soft/40"
          }`}
        >
          <span
            aria-hidden
            className="mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand-soft text-brand"
          >
            <UploadCloud className="h-6 w-6" />
          </span>
          <span className="text-sm font-medium text-foreground">
            Drag a file here, or click to browse
          </span>
          <span className="mt-1 text-xs text-text-secondary">PDF, PNG or JPG</span>
        </button>

        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-foreground">
            <HardDrive aria-hidden className="h-4 w-4 text-text-secondary" /> Storage
          </div>
          <p className="font-display text-2xl font-semibold tabular-nums text-foreground">
            {fmtSize(usedBytes)}
          </p>
          <p className="mt-0.5 text-xs text-text-secondary">
            {files.length} file{files.length === 1 ? "" : "s"} in this workspace
          </p>
          <div aria-hidden className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-brand"
              style={{
                width: `${Math.min(100, (usedBytes / (200 * 1024 * 1024)) * 100)}%`,
              }}
            />
          </div>
        </Card>
      </div>

      {files.length > 0 && (
        <div className="relative mt-4 max-w-sm">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-secondary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search reports…"
            aria-label="Search reports"
            className="h-10 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm outline-none transition-colors focus:border-brand/50"
          />
        </div>
      )}

      <div className="mt-4">
        {status === "LoadingFirstPage" ? (
          <SkeletonGroup
            label="Loading your reports"
            className="grid grid-cols-2 gap-3 md:grid-cols-4"
          >
            {["a", "b", "c", "d", "e", "f", "g", "h"].map((k) => (
              <Skeleton key={k} className="h-28 rounded-xl" />
            ))}
          </SkeletonGroup>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title={files.length === 0 ? "No reports yet" : "Nothing matches that"}
            description={
              files.length === 0
                ? "Upload a lab report, prescription or scan to keep it here."
                : "Try a different search term."
            }
            action={
              files.length === 0 ? (
                <Button type="button" onClick={() => inputRef.current?.click()}>
                  Upload a report
                </Button>
              ) : null
            }
          />
        ) : (
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
            {filtered.map((f) => {
              const Icon = iconFor(f.contentType);
              return (
                <li key={f._id}>
                  <Card variant="interactive" className="group relative h-full p-4">
                    <span
                      aria-hidden
                      className="mb-3 grid h-10 w-10 place-items-center rounded-lg bg-surface-2 text-text-secondary"
                    >
                      <Icon className="h-5 w-5" />
                    </span>
                    {f.url ? (
                      <a
                        href={f.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate text-sm font-medium text-foreground transition-colors hover:text-brand"
                      >
                        {f.name}
                      </a>
                    ) : (
                      <span className="block truncate text-sm font-medium text-foreground">
                        {f.name}
                      </span>
                    )}
                    <p className="mt-0.5 text-xs tabular-nums text-text-secondary">
                      {fmtSize(f.size)} · {new Date(f.createdAt).toLocaleDateString()}
                    </p>
                    {/* `focus-within` as well as hover: a delete button that
                        only appears on hover cannot be reached by keyboard. */}
                    <div className="absolute right-2 top-2 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                      <ConfirmButton
                        label={<Trash2 aria-hidden className="h-3.5 w-3.5" />}
                        className="grid h-7 w-7 place-items-center rounded-lg border border-border bg-card text-destructive transition-colors hover:bg-destructive/10"
                        title="Delete this report?"
                        description={`“${f.name}” will be permanently removed.`}
                        confirmLabel="Delete"
                        onConfirm={async () => {
                          await removeFile({ fileId: f._id });
                          toast.success("Report deleted");
                        }}
                      />
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {status === "CanLoadMore" && (
        <div className="mt-5 flex justify-center">
          <Button variant="outline" size="sm" onClick={() => loadMore(24)}>
            Load more
          </Button>
        </div>
      )}
      {status === "LoadingMore" && (
        <p className="mt-5 text-center text-sm text-text-secondary">Loading…</p>
      )}
    </PageShell>
  );
}
