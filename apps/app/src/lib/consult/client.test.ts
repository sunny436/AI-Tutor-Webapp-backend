/**
 * The API client: where requests go, and what rides on them.
 *
 *   bun apps/app/src/lib/consult/client.test.ts
 *
 * Offline. `fetch` is stubbed, so these assert OUR behaviour rather than a
 * backend's. Three things are worth pinning down:
 *
 *   1. every call goes to our own origin. Two of them used to go straight to the
 *      Python backend carrying a token the page had no way to refresh, which is
 *      the documented cause of a reported "AI service unavailable (401)".
 *   2. every turn carries `bot_id`. One backend serves several frontends, and
 *      that field is what selects the knowledge base.
 *   3. the mock provider returns a usable conversation with no backend at all,
 *      so a frontend developer needs no Python, Convex or API key.
 */

const results: [string, boolean, string][] = [];
const check = (name: string, ok: boolean, detail = "") => {
  results.push([name, ok, detail]);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
};

type Call = { url: string; body: Record<string, unknown>; headers: Record<string, string> };

/** Load client.ts fresh, with env applied before module evaluation. */
async function loadClient(provider: string, botId?: string) {
  process.env.NEXT_PUBLIC_CONSULT_PROVIDER = provider;
  if (botId) process.env.NEXT_PUBLIC_BOT_ID = botId;
  // Cache-bust so module-level env reads re-run.
  return import(`./client?v=${provider}-${botId ?? ""}-${Math.random()}`);
}

function stubFetch(calls: Call[], payload: unknown = {}) {
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
    let body: Record<string, unknown> = {};
    try {
      body = init?.body instanceof FormData ? { form: true } : JSON.parse(String(init?.body ?? "{}"));
    } catch {
      body = { unparsed: true };
    }
    calls.push({
      url: String(url),
      body,
      headers: (init?.headers ?? {}) as Record<string, string>,
    });
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

// --- 1. everything goes through our own origin -------------------------------
{
  const calls: Call[] = [];
  stubFetch(calls, { kind: "chat", answer: "ok", context: {}, sources: [] });
  const client = await loadClient("local");

  await client.postConsult({ problem: "hi" });
  check("consult posts to /api/consult", calls[0]?.url === "/api/consult", calls[0]?.url);

  calls.length = 0;
  await client.uploadDocument(new File(["x"], "r.pdf"), "tok");
  check(
    "upload posts to /api/upload, NOT the backend directly",
    calls[0]?.url === "/api/upload",
    calls[0]?.url,
  );
  check(
    "...so it no longer names AI_BACKEND_URL",
    !calls[0]?.url.includes("localhost:4000") && !calls[0]?.url.startsWith("http"),
    calls[0]?.url,
  );

  calls.length = 0;
  await client.transcribeAudio(new Blob(["x"], { type: "audio/webm" }), "tok");
  check(
    "transcribe posts to /api/transcribe, NOT the backend directly",
    calls[0]?.url === "/api/transcribe",
    calls[0]?.url,
  );
  check(
    "...and does not set Content-Type by hand (the boundary must survive)",
    !Object.keys(calls[0]?.headers ?? {}).some((h) => h.toLowerCase() === "content-type"),
    JSON.stringify(calls[0]?.headers),
  );
}

// --- 2. bot_id rides on every turn -------------------------------------------
{
  const calls: Call[] = [];
  stubFetch(calls, { kind: "chat", answer: "ok", context: {}, sources: [] });
  const client = await loadClient("local");

  await client.postConsult({ problem: "hi" });
  check("bot_id is sent", calls[0]?.body.bot_id === "ayurveda", String(calls[0]?.body.bot_id));

  calls.length = 0;
  await client.postConsult({ problem: "hi", conversationId: "c1" });
  check("conversationId still rides alongside it", calls[0]?.body.conversationId === "c1");

  calls.length = 0;
  await client.postConsult({ problem: "hi", bot_id: "explicit" } as never);
  check(
    "an explicitly passed bot_id is not overwritten",
    calls[0]?.body.bot_id === "explicit",
    String(calls[0]?.body.bot_id),
  );
}

{
  const calls: Call[] = [];
  stubFetch(calls, { kind: "chat", answer: "ok", context: {}, sources: [] });
  const client = await loadClient("local", "yoga");
  await client.postConsult({ problem: "hi" });
  check(
    "NEXT_PUBLIC_BOT_ID selects the bot",
    calls[0]?.body.bot_id === "yoga",
    String(calls[0]?.body.bot_id),
  );
  // Cleared rather than deleted: `BOT_ID` is `env || "ayurveda"`, so an empty
  // string restores the default without reaching for the `delete` operator.
  process.env.NEXT_PUBLIC_BOT_ID = "";
}

// --- 3. the mock provider needs no backend -----------------------------------
{
  const calls: Call[] = [];
  stubFetch(calls);
  const client = await loadClient("mock");

  check("provider resolves to mock", client.CONSULT_PROVIDER === "mock", client.CONSULT_PROVIDER);

  const first = await client.postConsult({ problem: "mujhe gas ho rahi hai" });
  check("mock makes NO network call at all", calls.length === 0, `${calls.length} calls`);
  check("mock asks a question first", first.kind === "chat", first.kind);
  check("mock renders no cards", first.intake === null);
  check("mock enters the gathering phase", first.context.phase === "gathering", first.context.phase);

  const second = await client.postConsult({ problem: "aaj se", context: first.context });
  const third = await client.postConsult({ problem: "spicy khana", context: second.context });
  check("mock reaches a plan after a few turns", third.kind === "answer", third.kind);
  check(
    "...with the six-section shape the UI renders",
    third.answer.includes("**Root Cause**") && third.answer.includes("**When To See A Doctor**"),
  );
  check("...and with citations to exercise the sources UI", third.sources.length === 2);

  // Streaming has no mock transport; it must degrade, not throw.
  const streamed = await client.postConsultStream({ problem: "hi" }, () => {});
  check("streaming falls back to the non-streaming mock", streamed.kind === "chat", streamed.kind);
  check("...still without a network call", calls.length === 0, `${calls.length} calls`);
}

const passed = results.filter(([, ok]) => ok).length;
console.log(`\n===== client: ${passed}/${results.length} passed =====`);
if (passed !== results.length) {
  console.log("\nFailing:");
  for (const [name, ok, detail] of results) if (!ok) console.log(`  - ${name}: ${detail}`);
}
process.exit(passed === results.length ? 0 : 1);
