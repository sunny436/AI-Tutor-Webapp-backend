import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * `convex-test` runs Convex functions in-process against a simulated backend, so
 * this suite needs no deployment, no network and no credentials. It requires the
 * edge runtime (matching Convex's own V8 environment) and `convex-test` inlined
 * rather than pre-bundled.
 *
 * PREVIOUSLY BROKEN ON WINDOWS, now fixed by the absolute `root` below.
 * The old failure: vitest's executor calls `executeId("/@vite/env")`, the id
 * reaches `pathToFileURL("/@vite/env")` → `fileURLToPath("file:///@vite/env")`,
 * and Windows throws "File URL path must be an absolute path" because the path
 * has no drive letter — reported as the misleading "No test suite found in file
 * …" for every file. It no longer reproduces on vitest 3.2.7 / vite-node 3.2.4:
 * all 39 tests collect and run here. Kept as a note because the symptom points
 * nowhere near the cause, and the next bump could bring it back.
 */
export default defineConfig({
  // Absolute, correctly-cased root — vite-node otherwise mis-resolves module ids
  // relative to the drive on Windows.
  root: fileURLToPath(new URL(".", import.meta.url)),
  test: {
    environment: "edge-runtime",
    // Vitest's 5s default is too tight for this suite, and the failure it
    // produces is misleading: two `username updates` tests timed out on roughly
    // one run in three while the same assertions passed on the others.
    //
    // Nothing in the product is slow. Every test calls `convexTest(schema,
    // modules)`, which stands up a fresh simulated backend and resolves the
    // whole `import.meta.glob` module graph — measured at 13s of collection plus
    // 23s across 39 tests on this machine. Whichever test happens to pay the
    // cold start can exceed 5s through no fault of its own.
    //
    // A flaky test sitting next to a security suite (RBAC, cross-tenant IDOR,
    // webhook replay) is worse than a slow one: it teaches people to re-run
    // instead of read, and that habit is how a real failure gets waved through.
    testTimeout: 30_000,
    // `@convex-dev/polar` is inlined so Vite resolves it rather than Node's ESM
    // loader: its client entry does `import "./polyfill"` with no file extension,
    // which is illegal in Node ESM and fails as "Cannot find module …/polyfill"
    // even though polyfill.js is right there. Vite's resolver adds the extension.
    server: { deps: { inline: ["convex-test", "@convex-dev/polar"] } },
    include: ["convex/**/*.test.ts"],
  },
});
