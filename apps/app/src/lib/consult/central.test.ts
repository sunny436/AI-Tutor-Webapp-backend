/**
 * The reply reader, checked against the shapes a central API realistically
 * returns.
 *
 *   bun apps/app/src/lib/consult/central.test.ts
 *
 * Pure and offline on purpose: this is the one piece of the migration that can
 * be wrong in a way the type system cannot catch, because it reads somebody
 * else's JSON. The two assertions that matter most are the last two — an
 * unrecognised shape must FAIL LOUDLY rather than render an empty bubble, since
 * an empty bubble looks like the assistant said nothing instead of like a
 * mapping that needs one line added.
 */

import { normalizeCentralResponse } from "./central";
import type { ConsultContext } from "./types";

const results: [string, boolean, string][] = [];
const check = (name: string, ok: boolean, detail = "") => {
  results.push([name, ok, detail]);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
};

const CTX = { v: 2, phase: "casual" } as unknown as ConsultContext;

const CARD = {
  id: "frequency",
  label: "How often?",
  type: "single",
  display: "chips",
  options: [
    { id: "rare", label: "Rarely" },
    { id: "blood", label: "Blood in stool", red_flag: true },
  ],
};

// 1. Best case: they already speak our shape.
{
  const out = normalizeCentralResponse(
    { kind: "intake", condition: "Acidity", intake: { note: "A few questions", questions: [CARD] } },
    null,
  );
  check("identical shape -> intake", out.kind === "intake", `kind=${out.kind}`);
  check("questions survive", out.intake?.questions.length === 1);
  check(
    "red_flag survives (a doctor warning depends on it)",
    out.intake?.questions[0]?.options[1]?.red_flag === true,
  );
}

// 2. Plain text under a different key, nested one level.
{
  const out = normalizeCentralResponse({ data: { reply: "Ghee helps digestion." } }, null);
  check("nested {data:{reply}} -> chat", out.kind === "chat" && out.answer.includes("Ghee"));
}

// 3. Questions at the top level rather than under `intake`.
{
  const out = normalizeCentralResponse({ questions: [CARD], condition: "Gas" }, null);
  check("top-level questions -> intake", out.kind === "intake" && out.condition === "Gas");
}

// 4. Cards under `cards`.
{
  const out = normalizeCentralResponse({ cards: [CARD] }, null);
  check("questions under `cards`", out.intake?.questions.length === 1);
}

// 5. Context is echoed back when the reply carries none, so a half-finished
//    intake is not silently reset by a reply that just did not mention state.
{
  const out = normalizeCentralResponse({ message: "ok" }, CTX);
  check("missing context falls back to ours", out.context?.phase === "casual");
}

// 6. An explicit escalation keeps its kind — the UI renders this differently.
{
  const out = normalizeCentralResponse({ kind: "escalation", message: "Please see a doctor." }, null);
  check("escalation kind preserved", out.kind === "escalation");
}

// 7. Unknown shape must THROW, naming the keys that arrived.
{
  let threw = "";
  try {
    normalizeCentralResponse({ foo: 1, bar: 2 }, null);
  } catch (error) {
    threw = (error as Error).message;
  }
  check("unrecognised shape throws", Boolean(threw), threw.slice(0, 80));
  check("error names the keys it saw", threw.includes("foo") && threw.includes("bar"));
}

// 8. A non-object reply must not slip through as an empty bubble.
{
  let threw = "";
  try {
    normalizeCentralResponse("just a string", null);
  } catch (error) {
    threw = (error as Error).message;
  }
  check("non-object reply throws", Boolean(threw));
}

const passed = results.filter(([, ok]) => ok).length;
console.log(`\n===== central adapter: ${passed}/${results.length} passed =====`);
if (passed !== results.length) process.exit(1);
