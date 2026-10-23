import { describe, expect, test } from "bun:test";

import { ApiError } from "@/lib/api/errors";
import type { LibraryFile } from "@/lib/api/types";
import { type AttachmentApi, AttachmentStore, type Chip, canSendDraft } from "./attachment-store";

function libraryFile(overrides: Partial<LibraryFile> = {}): LibraryFile {
  return {
    id: "f-1",
    filename: "notes.pdf",
    kind: "pdf",
    sizeBytes: 10,
    status: "processing",
    errorCode: null,
    retryable: false,
    createdAt: "2026-09-30T00:00:00Z",
    updatedAt: "2026-09-30T00:00:00Z",
    ...overrides,
  };
}

function setup(api: Partial<AttachmentApi> = {}) {
  const timers: (() => void)[] = [];
  const calls = { uploads: 0, gets: 0 };
  const full: AttachmentApi = {
    sha256Hex: async () => "abc",
    findFile: async () => null,
    uploadFile: async () => {
      calls.uploads += 1;
      return libraryFile();
    },
    getFile: async () => {
      calls.gets += 1;
      return libraryFile({ status: "ready" });
    },
    retryFile: async () => libraryFile({ status: "processing" }),
    ...api,
  };
  const store = new AttachmentStore(full, (key) => key, { now: () => 0, later: (run) => void timers.push(run) });
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  const tick = async () => {
    const run = timers.shift();
    run?.();
    await flush();
    await flush();
  };
  return { store, calls, flush, tick, timers };
}

const pdf = () => new File(["%PDF-1.4 hello"], "notes.pdf", { type: "application/pdf" });

describe("canSendDraft", () => {
  const chip = (state: Chip["state"]) => ({ state }) as Chip;
  test("sends only with text, no stream, and every file ready", () => {
    const base = { text: "hi", streaming: false, tooLong: false };
    expect(canSendDraft({ ...base, chips: [] })).toBe(true);
    expect(canSendDraft({ ...base, chips: [chip("ready")] })).toBe(true);
    for (const state of ["hashing", "uploading", "processing", "failed", "stored", "upload_failed", "missing"] as const) {
      expect(canSendDraft({ ...base, chips: [chip("ready"), chip(state)] })).toBe(false);
    }
    expect(canSendDraft({ ...base, text: "   ", chips: [] })).toBe(false);
    expect(canSendDraft({ ...base, streaming: true, chips: [] })).toBe(false);
  });
});

describe("AttachmentStore", () => {
  test("upload → reading → ready, polled until then", async () => {
    const { store, calls, flush, tick } = setup();
    store.add("c1", [pdf()]);
    await flush();
    await flush();
    expect(calls.uploads).toBe(1);
    expect(store.get("c1")[0]?.state).toBe("processing");
    await tick();
    expect(store.get("c1")[0]?.state).toBe("ready");
    expect(store.take("c1")).toEqual([{ fileId: "f-1", filename: "notes.pdf" }]);
    expect(store.get("c1")).toEqual([]);
  });

  test("bytes already in the library are not uploaded again", async () => {
    const { store, calls, flush } = setup({ findFile: async () => libraryFile({ status: "ready" }) });
    store.add("c1", [pdf()]);
    await flush();
    await flush();
    expect(calls.uploads).toBe(0);
    expect(store.get("c1")[0]?.state).toBe("ready");
  });

  test("the same bytes, failed before for a passing reason, are tried again", async () => {
    const failed = libraryFile({ status: "failed", errorCode: "embedding_failed", retryable: true });
    const { store, calls, flush } = setup({ findFile: async () => failed });
    store.add("c1", [pdf()]);
    await flush();
    await flush();
    expect(calls.uploads).toBe(0);
    expect(store.get("c1")[0]?.state).toBe("processing");
  });

  test("wrong types, oversized files and more than five are refused before any upload", () => {
    const { store } = setup();
    const result = store.add("c1", [
      new File(["x"], "virus.exe"),
      new File([new Uint8Array(3 * 1024 * 1024)], "big.txt"),
      ...Array.from({ length: 6 }, (_, i) => new File(["x"], `n${i}.txt`)),
    ]);
    expect(result.rejected.map((r) => r.reason)).toEqual(["type", "size", "count"]);
    expect(store.get("c1")).toHaveLength(5);
  });

  test("a full storage fails the upload, keeps the file for a retry, and opens the dialog", async () => {
    let full = 0;
    const { store, flush } = setup({
      uploadFile: async () => {
        throw new ApiError(409, "storage_quota_exceeded");
      },
    });
    store.onStorageFull = () => {
      full += 1;
    };
    store.add("c1", [pdf()]);
    await flush();
    await flush();
    const chip = store.get("c1")[0];
    expect(chip?.state).toBe("upload_failed");
    expect(chip?.errorCode).toBe("storage_quota_exceeded");
    expect(full).toBe(1);
  });

  test("a deleted file shows as missing; remove only detaches", async () => {
    const { store, tick, flush } = setup({
      getFile: async () => {
        throw new ApiError(404, "not_found");
      },
    });
    store.attachExisting("c1", libraryFile({ status: "processing" }));
    await tick();
    expect(store.get("c1")[0]?.state).toBe("missing");
    store.remove("c1", store.get("c1")[0]?.localId ?? "");
    await flush();
    expect(store.get("c1")).toEqual([]);
  });

  test("a refused send gives the files back and checks them again", async () => {
    const { store, calls, flush } = setup();
    store.restore("c1", [{ fileId: "f-1", filename: "notes.pdf" }]);
    await flush();
    expect(store.get("c1")[0]?.fileId).toBe("f-1");
    expect(calls.gets).toBe(1);
  });

  test("uploads run one at a time", async () => {
    let running = 0;
    let most = 0;
    const { store, flush } = setup({
      uploadFile: async () => {
        running += 1;
        most = Math.max(most, running);
        await new Promise((resolve) => setTimeout(resolve, 1));
        running -= 1;
        return libraryFile({ id: `f-${Math.random()}`, status: "ready" });
      },
    });
    store.add("c1", [pdf(), new File(["b"], "b.txt"), new File(["c"], "c.txt")]);
    for (let i = 0; i < 20; i += 1) await flush();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(most).toBe(1);
  });
});
