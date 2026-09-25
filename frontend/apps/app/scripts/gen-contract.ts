/**
 * Writes src/lib/api/contract.gen.ts from the repository's docs/openapi.json.
 * Run by `bun run contract` (repository root) after the backend regenerates the contract.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { renderContract } from "../src/lib/api/contract-render";

const app = join(import.meta.dir, "..");
const openapi = JSON.parse(readFileSync(join(app, "../../../docs/openapi.json"), "utf8"));
const target = join(app, "src/lib/api/contract.gen.ts");
writeFileSync(target, renderContract(openapi));
console.log(`wrote ${target}`);
