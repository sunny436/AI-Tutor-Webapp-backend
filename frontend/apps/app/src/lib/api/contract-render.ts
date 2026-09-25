/**
 * Renders `contract.gen.ts` from the backend's contract, `docs/openapi.json`.
 *
 * The backend is the single source of truth for enums and limits: request fields'
 * allowed values, lengths, numeric ranges and list sizes. The web app reads them from
 * the generated file instead of restating them, so a backend change reaches the UI (or
 * fails the build) in the same commit. `bun run contract` regenerates the file;
 * `contract.gen.test.ts` fails when it is stale.
 *
 * Pure and deterministic (sorted keys, stable formatting), so the test can compare the
 * rendered text with the committed file byte for byte.
 */

type JsonSchema = {
  enum?: unknown[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  pattern?: string;
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  type?: string;
};

type OpenApi = { components?: { schemas?: Record<string, JsonSchema> } };

const KEYS = ["enum", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "pattern"] as const;

/** `X | null` fields are `anyOf: [X, {type: "null"}]`; the constraints live on X. */
function unwrap(schema: JsonSchema): JsonSchema {
  const branches = schema.anyOf?.filter((branch) => branch.type !== "null") ?? [];
  return branches.length === 1 && branches[0] ? branches[0] : schema;
}

function constraints(schema: JsonSchema): Record<string, unknown> | null {
  const field = unwrap(schema);
  const out: Record<string, unknown> = {};
  for (const key of KEYS) {
    if (field[key] !== undefined) out[key] = field[key];
  }
  const items = field.items ? constraints(field.items) : null;
  if (items) out.items = items;
  return Object.keys(out).length ? out : null;
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((key) => [key, sorted((value as Record<string, unknown>)[key])]),
    );
  }
  return value;
}

export function renderContract(openapi: OpenApi): string {
  const contract: Record<string, Record<string, unknown>> = {};
  for (const [name, schema] of Object.entries(openapi.components?.schemas ?? {})) {
    const fields: Record<string, unknown> = {};
    for (const [field, property] of Object.entries(schema.properties ?? {})) {
      const found = constraints(property);
      if (found) fields[field] = found;
    }
    if (Object.keys(fields).length) contract[name] = fields;
  }
  return [
    "// GENERATED from docs/openapi.json by scripts/gen-contract.ts. Do not edit: run `bun run contract`.",
    "// The backend owns these enums and limits; the web app reads them from here.",
    "",
    `export const CONTRACT = ${JSON.stringify(sorted(contract), null, 2)} as const;`,
    "",
  ].join("\n");
}
