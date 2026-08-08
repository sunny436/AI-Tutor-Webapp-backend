import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * `convex-test` runs Convex functions in-process against a simulated backend, so
 * this suite needs no deployment, no network and no credentials. It requires the
 * edge runtime (matching Convex's own V8 environment) and `convex-test` inlined
 * rather than pre-bundled.
 *
 * KNOWN ISSUE — this suite does not currently run on Windows.
 * Vitest 3.2.7's executor unconditionally calls `executeId("/@vite/env")`, but the
 * vite-node build it pins (3.2.4) only stubs `/@vite/client`. The unstubbed id
 * reaches `pathToFileURL("/@vite/env")` → `fileURLToPath("file:///@vite/env")`,
 * which throws "File URL path must be an absolute path" on Windows because the
 * path has no drive letter. Vitest reports that as the misleading
 * "No test suite found in file …" for every file. POSIX is unaffected (a leading
 * "/" is already an absolute path there), so this runs correctly in CI and on
 * macOS/Linux. Re-check after a vitest/vite-node bump.
 */
export default defineConfig({
  // Absolute, correctly-cased root — vite-node otherwise mis-resolves module ids
  // relative to the drive on Windows.
  root: fileURLToPath(new URL(".", import.meta.url)),
  test: {
    environment: "edge-runtime",
    server: { deps: { inline: ["convex-test"] } },
    include: ["convex/**/*.test.ts"],
  },
});
