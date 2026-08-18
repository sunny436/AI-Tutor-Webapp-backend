/**
 * The TypeScript must not fall behind the backend's published contract.
 *
 *   bun apps/app/src/lib/consult/contract.test.ts
 *
 * `types.ts` mirrors `backend-python/src/consult/schema.py` BY HAND. In one
 * repository that survives on review; across two repositories owned by two teams it
 * will not. The symptom is not a build error — it is a field arriving as
 * `undefined` in production, on a health product, with nothing failing loudly.
 *
 * The backend publishes what it actually promises (`scripts/export_contract.py`),
 * that file is committed and SHIPS WITH THIS APP, and this suite asserts the
 * TypeScript still satisfies it. So the check runs unchanged in a repository that
 * contains no Python at all — which is the whole point.
 *
 * WHY THE ASSERTIONS ARE WRITTEN OUT BY HAND
 * TypeScript types do not exist at runtime, so nothing here can reflect over
 * `ConsultResult`. Instead each value the UI actually branches on is asserted
 * against the contract explicitly. That is narrower than a generated type — and it
 * is aimed at the failure that actually happens: the backend changes a phase name
 * or a source prefix, and the frontend keeps compiling while behaving wrongly.
 */

import contract from "@/content/consult-contract.json";
import { CONSULTING, type ConsultKind, type ConsultPhase } from "./types";

const results: [string, boolean, string][] = [];
const check = (name: string, ok: boolean, detail = "") => {
  results.push([name, ok, detail]);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
};

const same = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join("|") === [...b].sort().join("|");

// --- the unions the UI branches on -------------------------------------------
// Written out as literal arrays because the type itself is erased at runtime. If
// someone edits the union in types.ts they must edit these too, and the test then
// tells them whether the backend agrees.
const TS_KINDS: ConsultKind[] = ["chat", "intake", "answer", "escalation", "error"];
const TS_PHASES: ConsultPhase[] = [
  "idle",
  "greeted",
  "casual",
  "gathering",
  "collecting",
  "choosing",
  "completed",
];

check(
  "ConsultKind matches the backend exactly",
  same(TS_KINDS, contract.enums.kind),
  `ts=[${TS_KINDS}] backend=[${contract.enums.kind}]`,
);
check(
  "ConsultPhase matches the backend exactly",
  same(TS_PHASES, contract.enums.phase),
  `ts=[${TS_PHASES}] backend=[${contract.enums.phase}]`,
);

// The single easiest thing to get wrong, and the most expensive: send `problem`
// while a consultation is open and every follow-up starts a new one.
check(
  "CONSULTING matches the backend's phase group",
  same([...CONSULTING], contract.phase_groups.consulting),
  `ts=[${CONSULTING}] backend=[${contract.phase_groups.consulting}]`,
);

// Retired, but a conversation persisted before the card intake was removed still
// carries one. Dropping them from the union makes `load_context` reset the chat.
check(
  "the retired card phases are still in the TS union",
  contract.phase_groups.legacy.every((p) => (TS_PHASES as string[]).includes(p)),
  contract.phase_groups.legacy.join(", "),
);

// --- fields the UI reads without guarding ------------------------------------
const resultFields = Object.keys(contract.models.ConsultResult);
for (const field of ["kind", "condition", "message", "answer", "intake", "context", "sources"]) {
  check(`ConsultResult.${field} is published by the backend`, resultFields.includes(field));
}

const contextFields = Object.keys(contract.models.ConsultContext);
for (const field of ["phase", "chat_history", "language", "condition", "symptoms"]) {
  check(`ConsultContext.${field} is published by the backend`, contextFields.includes(field));
}

// --- citations ----------------------------------------------------------------
// answer-sources.tsx groups on these prefixes. A namespace the backend adds that
// the UI does not know falls into the "knowledge" bucket and is then miscounted as
// a curated Ayurveda note — a false claim about where an answer came from.
const UI_NAMESPACES = ["knowledge", "report", "graphrag", "memory"];
check(
  "every source namespace the backend emits is handled by the UI",
  same(UI_NAMESPACES, contract.source_namespaces),
  `ui=[${UI_NAMESPACES}] backend=[${contract.source_namespaces}]`,
);

// --- request side --------------------------------------------------------------
for (const field of ["problem", "freeText", "context", "conversationId", "bot_id"]) {
  check(`the backend accepts ${field}`, contract.request_fields.includes(field));
}

const passed = results.filter(([, ok]) => ok).length;
console.log(`\n===== contract (frontend): ${passed}/${results.length} passed =====`);
if (passed !== results.length) {
  console.log("\nFailing:");
  for (const [name, ok, detail] of results) if (!ok) console.log(`  - ${name}: ${detail}`);
}
process.exit(passed === results.length ? 0 : 1);
