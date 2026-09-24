import type { FullConfig } from "@playwright/test";

import { API_URL, MAILPIT_URL, assertLoopback } from "./env";

/**
 * Before any test: everything must be local, and the local services must be up.
 * Fails fast with what to start, rather than 20 tests timing out one by one.
 */
export default async function globalSetup(config: FullConfig): Promise<void> {
  for (const project of config.projects) {
    if (project.use.baseURL) assertLoopback(`baseURL (${project.name})`, project.use.baseURL);
  }
  assertLoopback("E2E_API_URL", API_URL);
  assertLoopback("E2E_MAILPIT_URL", MAILPIT_URL);

  const ready = await fetch(`${API_URL}/ready`).catch(() => null);
  const body = ready?.ok ? await ready.json().catch(() => null) : null;
  if (body?.status !== "ok") {
    throw new Error(
      `The backend is not ready at ${API_URL}/ready. Start it with the fake LLM (see apps/app/playwright.config.ts), or create backend/.venv so the suite starts it (or set E2E_BACKEND_DIR).`,
    );
  }

  const mail = await fetch(`${MAILPIT_URL}/api/v1/info`).catch(() => null);
  if (!mail?.ok) {
    throw new Error(`Mailpit is not reachable at ${MAILPIT_URL}. The suite reads sign-up and reset codes from it.`);
  }
}
