/**
 * Files attached to unsent messages, per chat, and their way to "ready".
 *
 * Lives beside the chat store (ChatProvider), not in the composer, so an upload keeps going and
 * its status keeps updating while the student is in Settings or the File Library. In memory only.
 *
 *   add → hashing → (already in the library? use it) → uploading % → processing → ready
 *                                                                               ↘ failed / stored
 * One upload at a time (the rest wait their turn). Each file being read is polled until it is
 * ready or failed. The server decides; this only reflects it, so "Send" waits for every chip.
 */

import { type ApiError, isAbortError } from "@/lib/api/errors";
import { fileTypeOf } from "@/lib/api/files";
import { ATTACHMENTS_MAX, type FileKind, type LibraryFile, type MessageAttachment } from "@/lib/api/types";

export type ChipState =
  | "hashing"
  | "uploading"
  | "processing"
  | "ready"
  | "failed"
  | "stored"
  | "upload_failed"
  | "missing";

export type Chip = Readonly<{
  localId: string;
  name: string;
  size: number;
  kind: FileKind | null;
  state: ChipState;
  /** 0..1 while uploading. */
  progress: number;
  fileId: string | null;
  /** A processing failure (FileOut.errorCode) or an upload's API error code. */
  errorCode: string | null;
  retryable: boolean;
}>;

export type AttachmentApi = {
  sha256Hex: (file: Blob) => Promise<string>;
  findFile: (sha256: string) => Promise<LibraryFile | null>;
  uploadFile: (file: File, options: { onProgress?: (fraction: number) => void; signal?: AbortSignal }) => Promise<LibraryFile>;
  getFile: (fileId: string) => Promise<LibraryFile>;
  retryFile: (fileId: string) => Promise<LibraryFile>;
};

export type AddResult = { rejected: { name: string; reason: "type" | "size" | "count" }[] };

const POLL_MS = 1500;
/** After this long a file still being read is checked less often (the queue can be long), never given up on. */
const POLL_SLOW_AFTER_MS = 2 * 60 * 1000;
const POLL_SLOW_MS = 10_000;
const EMPTY: readonly Chip[] = Object.freeze([]);

/** Send is allowed only when every attached file is ready (the API refuses anything else too). */
export function canSendDraft(input: { text: string; streaming: boolean; tooLong: boolean; chips: readonly Chip[] }) {
  return Boolean(input.text.trim()) && !input.streaming && !input.tooLong && input.chips.every((c) => c.state === "ready");
}

function stateOf(file: LibraryFile): ChipState {
  return file.status;
}

export class AttachmentStore {
  private chips = new Map<string, readonly Chip[]>();
  private listeners = new Map<string, Set<() => void>>();
  private blobs = new Map<string, File>();
  private uploads = new Map<string, AbortController>();
  private queue: { key: string; localId: string }[] = [];
  private uploading = false;
  private polls = new Map<string, { until: number }>();
  private counter = 0;

  /** Called when an upload is refused because the student's storage is full. */
  onStorageFull?: () => void;

  constructor(
    private readonly api: AttachmentApi,
    private readonly resolve: (key: string) => string = (key) => key,
    private readonly clock: { now: () => number; later: (run: () => void, ms: number) => void } = {
      now: () => Date.now(),
      later: (run, ms) => {
        setTimeout(run, ms);
      },
    },
  ) {}

  // ---------------------------------------------------------------- reading
  get(key: string): readonly Chip[] {
    return this.chips.get(this.resolve(key)) ?? EMPTY;
  }

  subscribe(key: string, listener: () => void): () => void {
    const canonical = this.resolve(key);
    let set = this.listeners.get(canonical);
    if (!set) {
      set = new Set();
      this.listeners.set(canonical, set);
    }
    set.add(listener);
    return () => {
      set.delete(listener);
    };
  }

  // ---------------------------------------------------------------- changes
  add(key: string, files: Iterable<File>): AddResult {
    const canonical = this.resolve(key);
    const rejected: AddResult["rejected"] = [];
    const next = [...this.get(canonical)];
    for (const file of files) {
      const type = fileTypeOf(file.name);
      if (!type) rejected.push({ name: file.name, reason: "type" });
      else if (file.size > type.maxBytes) rejected.push({ name: file.name, reason: "size" });
      else if (next.length >= ATTACHMENTS_MAX) rejected.push({ name: file.name, reason: "count" });
      else {
        const localId = `att:${++this.counter}`;
        this.blobs.set(localId, file);
        next.push({
          localId,
          name: file.name,
          size: file.size,
          kind: type.kind,
          state: "hashing",
          progress: 0,
          fileId: null,
          errorCode: null,
          retryable: false,
        });
        this.queue.push({ key: canonical, localId });
      }
    }
    this.set(canonical, next);
    void this.pump();
    return { rejected };
  }

  /** A file already in the library ("Ask in chat"). */
  attachExisting(key: string, file: LibraryFile): void {
    const canonical = this.resolve(key);
    const current = this.get(canonical);
    if (current.some((chip) => chip.fileId === file.id) || current.length >= ATTACHMENTS_MAX) return;
    const chip: Chip = {
      localId: `att:${++this.counter}`,
      name: file.filename,
      size: file.sizeBytes,
      kind: file.kind,
      state: stateOf(file),
      progress: 1,
      fileId: file.id,
      errorCode: file.errorCode,
      retryable: file.retryable,
    };
    this.set(canonical, [...current, chip]);
    if (chip.state === "processing") this.poll(file.id);
  }

  /** A new chat got its conversation id: its files follow it (they were keyed by the draft). */
  rekey(from: string, to: string): void {
    const moved = this.chips.get(from);
    if (!moved || from === to) return;
    this.chips.delete(from);
    this.set(to, [...(this.chips.get(to) ?? []), ...moved]);
    for (const listener of this.listeners.get(from) ?? []) listener();
  }

  /** Check every file still being read again now (the window regained focus). */
  refreshReading(): void {
    const ids = new Set<string>();
    for (const list of this.chips.values()) {
      for (const chip of list) if (chip.state === "processing" && chip.fileId) ids.add(chip.fileId);
    }
    for (const id of ids) void this.refresh(id);
  }

  /** Take the chip off this message. The file stays in the File Library (only deleting there removes it). */
  remove(key: string, localId: string): void {
    const canonical = this.resolve(key);
    this.uploads.get(localId)?.abort();
    this.queue = this.queue.filter((item) => item.localId !== localId);
    this.blobs.delete(localId);
    this.set(
      canonical,
      this.get(canonical).filter((chip) => chip.localId !== localId),
    );
  }

  async retry(key: string, localId: string): Promise<void> {
    const canonical = this.resolve(key);
    const chip = this.get(canonical).find((c) => c.localId === localId);
    if (!chip) return;
    if (chip.state === "upload_failed" && this.blobs.has(localId)) {
      this.patch(canonical, localId, { state: "hashing", progress: 0, errorCode: null });
      this.queue.push({ key: canonical, localId });
      void this.pump();
      return;
    }
    if (chip.state === "failed" && chip.retryable && chip.fileId) {
      try {
        this.applyFile(await this.api.retryFile(chip.fileId));
      } catch (error) {
        this.patch(canonical, localId, { retryable: false, errorCode: (error as ApiError).code ?? chip.errorCode });
      }
    }
  }

  /** The ready files, for sending; the chips leave the composer. */
  take(key: string): MessageAttachment[] {
    const canonical = this.resolve(key);
    const ready = this.get(canonical).filter((chip) => chip.state === "ready" && chip.fileId);
    for (const chip of ready) this.blobs.delete(chip.localId);
    this.set(canonical, []);
    return ready.map((chip) => ({ fileId: chip.fileId, filename: chip.name }));
  }

  /** A send was refused before it existed: the chips come back, and their state is checked again. */
  restore(key: string, attachments: MessageAttachment[]): void {
    const canonical = this.resolve(key);
    const current = this.get(canonical);
    const back: Chip[] = attachments
      .filter((a) => a.fileId && !current.some((chip) => chip.fileId === a.fileId))
      .map((a) => ({
        localId: `att:${++this.counter}`,
        name: a.filename,
        size: 0,
        kind: fileTypeOf(a.filename)?.kind ?? null,
        state: "ready",
        progress: 1,
        fileId: a.fileId,
        errorCode: null,
        retryable: false,
      }));
    this.set(canonical, [...back, ...current]);
    for (const chip of back) if (chip.fileId) void this.refresh(chip.fileId);
  }

  // ---------------------------------------------------------------- internals
  private set(canonical: string, chips: readonly Chip[]): void {
    if (chips.length === 0) this.chips.delete(canonical);
    else this.chips.set(canonical, chips);
    for (const listener of this.listeners.get(canonical) ?? []) listener();
  }

  private patch(canonical: string, localId: string, change: Partial<Chip>): void {
    const current = this.get(canonical);
    if (!current.some((chip) => chip.localId === localId)) return;
    this.set(
      canonical,
      current.map((chip) => (chip.localId === localId ? { ...chip, ...change } : chip)),
    );
  }

  private where(localId: string): string | null {
    for (const [key, list] of this.chips) if (list.some((chip) => chip.localId === localId)) return key;
    return null;
  }

  /** A file's latest state reaches every chip that shows it. */
  private applyFile(file: LibraryFile): void {
    for (const [key, list] of this.chips) {
      if (!list.some((chip) => chip.fileId === file.id)) continue;
      this.set(
        key,
        list.map((chip) =>
          chip.fileId === file.id
            ? { ...chip, state: stateOf(file), errorCode: file.errorCode, retryable: file.retryable, progress: 1 }
            : chip,
        ),
      );
    }
    if (file.status === "processing") this.poll(file.id);
  }

  private async pump(): Promise<void> {
    if (this.uploading) return;
    this.uploading = true;
    try {
      while (this.queue.length) {
        const next = this.queue.shift();
        if (next) await this.upload(next.localId);
      }
    } finally {
      this.uploading = false;
    }
  }

  private async upload(localId: string): Promise<void> {
    const file = this.blobs.get(localId);
    let key = this.where(localId);
    if (!file || !key) return;
    const controller = new AbortController();
    this.uploads.set(localId, controller);
    try {
      // The dedup check needs WebCrypto (secure pages only); without it the server dedups anyway.
      const existing = globalThis.crypto?.subtle ? await this.api.findFile(await this.api.sha256Hex(file)) : null;
      key = this.where(localId);
      if (!key) return; // removed meanwhile
      let stored = existing;
      if (existing?.status === "failed" && existing.retryable) {
        // The same bytes failed before for a passing reason (e.g. reading was down): try them again.
        stored = await this.api.retryFile(existing.id).catch(() => existing);
      }
      if (!stored) {
        this.patch(key, localId, { state: "uploading", progress: 0 });
        stored = await this.api.uploadFile(file, {
          signal: controller.signal,
          onProgress: (fraction) => {
            const at = this.where(localId);
            if (at) this.patch(at, localId, { progress: fraction });
          },
        });
      }
      key = this.where(localId);
      if (!key) return;
      if (this.get(key).some((chip) => chip.fileId === stored.id && chip.localId !== localId)) {
        this.remove(key, localId); // the same file is already on this message
        return;
      }
      this.patch(key, localId, { fileId: stored.id });
      this.blobs.delete(localId);
      this.applyFile(stored);
    } catch (error) {
      if (isAbortError(error)) return;
      const code = (error as ApiError).code ?? "unknown";
      const at = this.where(localId);
      if (at) this.patch(at, localId, { state: "upload_failed", errorCode: code, retryable: true });
      if (code === "storage_quota_exceeded") this.onStorageFull?.();
    } finally {
      this.uploads.delete(localId);
    }
  }

  private poll(fileId: string): void {
    if (this.polls.has(fileId)) return;
    const started = this.clock.now();
    const next = () => (this.clock.now() - started > POLL_SLOW_AFTER_MS ? POLL_SLOW_MS : POLL_MS);
    const tick = async () => {
      if (!this.polls.has(fileId)) return;
      const shown = [...this.chips.values()].some((list) => list.some((chip) => chip.fileId === fileId));
      if (!shown) {
        this.polls.delete(fileId);
        return;
      }
      const done = await this.refresh(fileId);
      if (done) this.polls.delete(fileId);
      else if (this.polls.has(fileId)) this.clock.later(() => void tick(), next());
    };
    this.polls.set(fileId, { until: started });
    this.clock.later(() => void tick(), POLL_MS);
  }

  /** True when the file will not change by itself any more. */
  private async refresh(fileId: string): Promise<boolean> {
    try {
      const file = await this.api.getFile(fileId);
      this.applyFile(file);
      return file.status !== "processing";
    } catch (error) {
      if ((error as ApiError).status === 404) {
        for (const [key, list] of this.chips) {
          if (list.some((chip) => chip.fileId === fileId)) {
            this.set(
              key,
              list.map((chip) => (chip.fileId === fileId ? { ...chip, state: "missing" as const } : chip)),
            );
          }
        }
        return true;
      }
      return false; // offline for a moment: keep polling
    }
  }
}
