/**
 * The File Library (docs/api-contract.md, "Files"): upload, list, retry, delete.
 *
 * The API decides everything (types by name and content, sizes, the 100 MB storage, duplicates).
 * The limits below only let the UI refuse early with a clear message.
 */

import { ApiError } from "./errors";
import { callRoute, notifyUnauthorized, urlFor } from "./http";
import type { FileKind, FileList, LibraryFile } from "./types";

const MB = 1024 * 1024;

/** Extension → what the API accepts (mirrors app/files/service.py TYPES; UX only). */
export const FILE_TYPES: Record<string, { kind: FileKind; maxBytes: number }> = {
  ".pdf": { kind: "pdf", maxBytes: 25 * MB },
  ".docx": { kind: "docx", maxBytes: 25 * MB },
  ".pptx": { kind: "pptx", maxBytes: 25 * MB },
  ".xlsx": { kind: "xlsx", maxBytes: 10 * MB },
  ".csv": { kind: "csv", maxBytes: 2 * MB },
  ".txt": { kind: "txt", maxBytes: 2 * MB },
  ".md": { kind: "md", maxBytes: 2 * MB },
  ".markdown": { kind: "md", maxBytes: 2 * MB },
  ".png": { kind: "image", maxBytes: 10 * MB },
  ".jpg": { kind: "image", maxBytes: 10 * MB },
  ".jpeg": { kind: "image", maxBytes: 10 * MB },
  ".webp": { kind: "image", maxBytes: 10 * MB },
};

/** For `<input type="file" accept>`. */
export const FILE_ACCEPT = Object.keys(FILE_TYPES).join(",");

export function fileTypeOf(name: string): { kind: FileKind; maxBytes: number } | null {
  const dot = name.lastIndexOf(".");
  return dot < 1 ? null : (FILE_TYPES[name.slice(dot).toLowerCase()] ?? null);
}

/** "12.4 MB", "820 KB": one binary formatter everywhere (the 100 MB storage is 100 × 1024 × 1024 bytes). */
export function formatBytes(bytes: number): string {
  if (bytes >= MB) return `${(bytes / MB).toFixed(bytes >= 10 * MB ? 0 : 1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

/** Hex SHA-256 of the file, read in the browser (lets an upload of known bytes be skipped). */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function listFiles(): Promise<FileList> {
  return callRoute("GET /v1/files");
}

/** The student's file with exactly these bytes, if the library has it. */
export async function findFile(sha256: string): Promise<LibraryFile | null> {
  const found = await callRoute<FileList>("GET /v1/files", { query: { sha256 } });
  return found.items[0] ?? null;
}

export function getFile(fileId: string): Promise<LibraryFile> {
  return callRoute("GET /v1/files/{file_id}", { params: { file_id: fileId } });
}

/** Where the browser reads a file's own bytes (an <img>, a PDF preview, a download): same origin. */
export function fileContentUrl(fileId: string): string {
  return `/api/v1/files/${encodeURIComponent(fileId)}/content`;
}

export function retryFile(fileId: string): Promise<LibraryFile> {
  return callRoute("POST /v1/files/{file_id}/retry", { params: { file_id: fileId } });
}

export function deleteFile(fileId: string): Promise<void> {
  return callRoute("DELETE /v1/files/{file_id}", { params: { file_id: fileId } });
}

/**
 * Upload one file as raw bytes. Resolves with the stored file (a new one, or the same bytes
 * already in the library). `onProgress` gets 0..1 while the bytes are sent.
 */
export function uploadFile(
  file: File,
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<LibraryFile> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", urlFor("POST /v1/files", { query: { filename: file.name } }));
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("Accept", "application/json");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total);
    };
    request.onload = () => {
      let body: unknown = null;
      try {
        body = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        body = null;
      }
      if (request.status >= 200 && request.status < 300 && body) {
        resolve(body as LibraryFile);
        return;
      }
      const envelope = (body as { error?: { code?: string; requestId?: string; fields?: [] } } | null)?.error;
      const error = new ApiError(request.status, envelope?.code ?? "", {
        requestId: envelope?.requestId,
        fields: envelope?.fields,
      });
      notifyUnauthorized(error);
      reject(error);
    };
    request.onerror = () => reject(new ApiError(0, "network_error"));
    request.onabort = () => reject(new DOMException("The upload was cancelled.", "AbortError"));
    if (options.signal) {
      if (options.signal.aborted) {
        request.abort();
        return;
      }
      options.signal.addEventListener("abort", () => request.abort(), { once: true });
    }
    request.send(file);
  });
}

/** Why a file could not be read, for people (codes from app/files: FileOut.errorCode). */
const FAILURES: Record<string, string> = {
  corrupt: "This file can't be opened. Save it again as a normal file and upload the new copy.",
  encrypted: "This file is password-protected. Remove the password and upload it again.",
  no_text: "No readable text was found in this file.",
  unreadable_text: "The text couldn't be read clearly (handwriting and blurry scans aren't supported).",
  invalid_encoding: "This text file isn't in a readable encoding. Save it as UTF-8 and try again.",
  too_many_pages: "This file has too many pages (the limit is 1,000). Split it and upload the parts.",
  too_many_scanned_pages: "This scanned file has more than 30 image-only pages. Split it or use a text PDF.",
  too_many_rows: "This spreadsheet is too big (up to 20 sheets of 5,000 rows and 50 columns).",
  content_too_large: "This file holds too much text to use at once. Split it and upload the parts.",
  timeout: "This file took too long to read. Split it into smaller files.",
  processing_interrupted: "Reading this file was interrupted too many times. Delete it and upload it again.",
  embedding_failed: "A temporary problem stopped this file from being read. Try again.",
  extractor_failed: "A temporary problem stopped this file from being read. Try again.",
  chunk_limit_reached: "Your library holds too much text to add this file. Delete some files, then try again.",
  files_capacity_reached: "File storage is full right now. Try again later.",
  model_changed: "This file needs to be read again. Try again.",
};

export function describeFileFailure(code: string | null): string {
  return (code && FAILURES[code]) || "This file couldn't be read.";
}
