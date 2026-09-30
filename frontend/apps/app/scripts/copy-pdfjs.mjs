// Serves pdf.js's worker (and its no-WebAssembly image decoders) as plain static files for the
// PDF preview (src/features/markdown/widgets/pdf-preview.tsx), under /pdfjs/<version>/.
//
// Not a webpack asset: Next 14 minifies emitted .mjs assets as scripts, which breaks this ES
// module worker. A folder per version, so a rolled-back build still finds the worker that matches
// its pdf.js (pdf.js refuses a worker of another version). Runs before `next dev` and `next build`;
// the folder is git-ignored and made again on every build.
import { chmodSync, copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const source = dirname(require.resolve("pdfjs-dist/package.json"));
const { version } = JSON.parse(readFileSync(join(source, "package.json"), "utf-8"));
const target = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "pdfjs", version);

const files = [
  ["legacy/build/pdf.worker.min.mjs", "pdf.worker.min.mjs"],
  ["wasm/jbig2_nowasm_fallback.js", "wasm/jbig2_nowasm_fallback.js"],
  ["wasm/openjpeg_nowasm_fallback.js", "wasm/openjpeg_nowasm_fallback.js"],
];
mkdirSync(join(target, "wasm"), { recursive: true });
for (const [from, to] of files) {
  copyFileSync(join(source, from), join(target, to));
  // Served to every browser: writable by its owner only (bun unpacks packages 0666).
  chmodSync(join(target, to), 0o644);
}
console.log(`pdf.js ${version}: worker and decoders copied to public/pdfjs/${version}/`);
