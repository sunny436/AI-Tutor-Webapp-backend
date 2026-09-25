import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

/**
 * Validated at build (next.config.mjs imports this file).
 *
 * The app builds with NO configuration at all: the API address defaults to the
 * loopback address the API binds to by contract (lib/server/config.ts), and
 * nothing here is required. Matches deploy/env/web.env.example at the repository root.
 *
 *   API_BASE_URL          server-only; where the chat API listens
 *   PREVIEW_FEATURES      server-only; "1" shows preview UI (sample data). Never in production.
 *   NEXT_PUBLIC_SITE_URL  the public origin (absolute metadata URLs)
 *   NEXT_PUBLIC_SENTRY_DSN optional; Sentry is only bundled when it is set
 */
export const env = createEnv({
  server: {
    API_BASE_URL: z.string().url().optional(),
    PREVIEW_FEATURES: z.enum(["0", "1"]).optional(),
  },
  client: {
    NEXT_PUBLIC_SITE_URL: z.string().url().optional(),
    NEXT_PUBLIC_SENTRY_DSN: z.string().optional(),
  },
  runtimeEnv: {
    API_BASE_URL: process.env.API_BASE_URL,
    PREVIEW_FEATURES: process.env.PREVIEW_FEATURES,
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
    NEXT_PUBLIC_SENTRY_DSN: process.env.NEXT_PUBLIC_SENTRY_DSN,
  },
  emptyStringAsUndefined: true,
  skipValidation: !!process.env.CI || !!process.env.SKIP_ENV_VALIDATION,
});
