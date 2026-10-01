/**
 * The identity side of Settings: the versioned profile, the photo, email change and devices.
 * Everything goes through the BFF (`callRoute`), except the photo upload, which needs upload
 * progress and so uses XMLHttpRequest against the same same-origin route.
 */

import { ApiError, isAbortError } from "./errors";
import { BFF_PREFIX, callRoute, notifyUnauthorized, urlFor } from "./http";
import { IMAGE_UPLOAD } from "./routes";
import type {
  EmailChangeRequest,
  EmailConfirmRequest,
  SessionList,
  UpdateProfileRequest,
  User,
} from "./types";

export const AVATAR_TYPES: readonly string[] = IMAGE_UPLOAD.types;
export const AVATAR_MAX_BYTES = IMAGE_UPLOAD.maxBytes;

/** A 409 `version_conflict` carries the profile as it is now. */
export function updateProfile(request: UpdateProfileRequest): Promise<User> {
  return callRoute("PATCH /v1/me/profile", {
    body: { version: request.version, set: request.set ?? {}, reset: request.reset ?? [] },
  });
}

/** The same-origin address of the user's photo (the API path behind the BFF). */
export function avatarSrc(user: Pick<User, "avatar">): string | null {
  return user.avatar ? `${BFF_PREFIX}${user.avatar.url}` : null;
}

/**
 * Upload a photo (JPEG, PNG or WebP, up to AVATAR_MAX_BYTES). The server re-encodes it; the
 * resolved user carries the new `avatar.url`. `onProgress` gets 0..1 while the file is sent.
 */
export function uploadAvatar(
  file: Blob,
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<User> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", urlFor("PUT /v1/me/avatar"));
    request.setRequestHeader("Content-Type", file.type);
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
        resolve(body as User);
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

export function removeAvatar(): Promise<User> {
  return callRoute("DELETE /v1/me/avatar");
}

/** Always 202 for an allowed request: a code goes to the new address if it is free. */
export function requestEmailChange(request: EmailChangeRequest): Promise<void> {
  return callRoute("POST /v1/me/email/change", {
    body: request.password ? { newEmail: request.newEmail, password: request.password } : { newEmail: request.newEmail },
  });
}

/** Moves the account to the new address and signs out every other device. */
export function confirmEmailChange(request: EmailConfirmRequest): Promise<User> {
  return callRoute("POST /v1/me/email/confirm", { body: { newEmail: request.newEmail, code: request.code } });
}

export function listSessions(): Promise<SessionList> {
  return callRoute("GET /v1/auth/sessions");
}

/** 409 `current_session` for the device in use (sign out instead). */
export function revokeSession(sessionId: string): Promise<void> {
  return callRoute("DELETE /v1/auth/sessions/{session_id}", { params: { session_id: sessionId } });
}

export { isAbortError };
