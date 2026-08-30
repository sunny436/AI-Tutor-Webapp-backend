# Roadmap — backend

Deferred work for THIS repository: the Python AI backend, the tunnel, the
self-hosted stacks and the browser suites.

**The frontend has its own roadmap.** Dashboard UX, Convex functions, auth, email
and the read-amplification work all moved to `ayurveda-frontend/ROADMAP.md` when
the frontend was split out. Nothing about `packages/` or `apps/app` belongs here
any more — if you are looking for it, look there.

---

## 1. GraphRAG is retrieval-only again — reversed 2026-08-30

The 2026-08-29 entry this replaces took GraphRAG's `/v1/answer` as the sole
answer-writer and deleted the local LLM, knowledge base, memory and
gathering conversation entirely. That has been undone by explicit decision:
GraphRAG is back to retrieval only (`/v1/search`, entities, relationships,
citations), and a local LLM (`src/consult/responder.py::write_plan`,
`prompts.PLAN_PROMPT`) writes every final answer from whatever the
retrieval pipeline assembles — GraphRAG's passages, the local knowledge
fallback, memory, and uploaded reports, each labeled by source.

Restored from git history (parent commit `b0c11cc`, the last one before the
09-29 deletion) rather than rebuilt from scratch — this repo's own commit
history already had measured, working versions of the retrieval pipeline,
the coverage gate, per-user document indexing, and the OpenRouter
error-handling state machine, so the work here was "restore and reintegrate,"
not "reinvent."

**Genuinely new, not restored** — this project never had it before:
- `src/consult/memory_manager.py` — curates which turns are worth
  remembering long-term (skip greetings, dedupe, extract a short fact),
  rather than replaying raw turns verbatim. The DECISION logic is complete;
  the PERSISTENCE step is **BLOCKED** — Convex's `/backend/user-memory`
  route only supports reading raw turns
  (`packages/backend/convex/memory.ts::recentTurns`), there is no mutation
  to write a curated fact. Needs a Convex-side change in the frontend repo
  before curated memory can actually be created; raw-turn memory
  (`PreviousConversationsRetriever`) works today without it.

**Measured stale, corrected in the same change:** `GRAPHRAG_TIMEOUT_S`'s
inherited default (2.5s) was failing every `/v1/search` call outright —
three direct, unwrapped calls measured 4.4-5.5s on 2026-08-30, nothing like
the "0.45-1.55s, re-measured after the vendor's extractor fix" this file
used to cite. Bumped to 6.5s. Worth asking the vendor whether their search
latency has regressed, rather than assuming either number is still current.

## 2. The contract changed again, and needs a frontend PR again

`docs/api-contract.md` is updated to match: `context` is meaningful again
(`phase` drives real routing), `POST /api/upload` gained `indexed` back
alongside yesterday's `text`/`truncated`, and `sources` can carry
`knowledge:`/`report:`/`memory:` prefixes again, not just `graphrag:`. The
`documents` field from yesterday still works unchanged — this is additive,
not another breaking change to that specific part.

## 3. Production-readiness

- **Named Cloudflare tunnel + real domain** — replaces the ephemeral
  `*.trycloudflare.com` URL, which changes whenever `cloudflared` restarts. This
  also unblocks Google OAuth in the frontend repo, which needs a stable redirect
  URI. `cloudflare/config.yml` and `cloudflare/zones.mjs` are here.
- **Strong `INSTANCE_SECRET`** for the self-hosted Convex backend — still the
  compose default in `self-hosted/`. Must change before any real use.
- **GlitchTip** (`self-hosted/glitchtip/`) is up and verified end to end. The stack
  lives here; the app-side DSN wiring lives in the frontend repo. Set
  `ALLOWED_HOSTS` before a real deployment.

## 4. Content

Back in scope. `data/knowledge/*.md` (29 notes) is restored and live again
as the local coverage-gate/fallback source — this repo's content decisions
matter again. Ayurvedic medicine names remain deferred by decision, not
oversight: `SYSTEM_RULES` rule 2 still forbids naming one, and the content
change and the prompt change would need to land together.

## Notes

- The 29 knowledge notes are restored (`git checkout b0c11cc --
  backend-python/data/knowledge`, 2026-08-30) — they are the source of
  truth again. `library.json` in the frontend repo is generated from them;
  edit the notes, never the JSON.
- **Removed from this roadmap:** "verify `deploy/setup.sh` on a clean VM". That
  directory was deleted in `3caf060` (10 Aug) and exists in neither repo, so the
  item had been asking for a check on a file that was already gone.
