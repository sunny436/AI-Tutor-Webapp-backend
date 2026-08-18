# Roadmap — backend

Deferred work for THIS repository: the Python AI backend, the tunnel, the
self-hosted stacks and the browser suites.

**The frontend has its own roadmap.** Dashboard UX, Convex functions, auth, email
and the read-amplification work all moved to `ayurveda-frontend/ROADMAP.md` when
the frontend was split out. Nothing about `packages/` or `apps/app` belongs here
any more — if you are looking for it, look there.

---

## 1. GraphRAG — built, tested, deliberately switched off

`GRAPHRAG_ENABLED=0`. The retriever is complete and verified against the live
service (23/23 tests, real DNS/TLS/auth/response). Two things block turning it on,
and **neither is ours to fix**:

- **Latency.** Five real calls: 2.43s, 3.72s, 5.59s, 7.28s, 3.07s. The per-retriever
  budget is `min(RETRIEVAL_TIMEOUT_S, GRAPHRAG_TIMEOUT_S)` = 3.0s, so most calls
  time out today. Raising it means raising `RETRIEVAL_TIMEOUT_S`, which the
  pipeline applies to EVERY retriever — a slow GraphRAG would then delay every
  consultation on the site. That is a trade to make deliberately, with numbers,
  not a value to nudge upward until the errors stop.
- **Graph quality.** 444 of 600 edges came back as bare `MENTIONS`, and `CAUSES`
  was inverted (`Root Cause --CAUSES--> Empty stomach with tea`). Reported to the
  vendor; awaiting their extractor fix. Until then `entities` and `edges` are
  read by nothing — see the long note in `src/retrieval/graphrag.py`, which
  records why feeding "X CAUSES Y" into a health prompt needs a safety review
  rather than a quiet edit.

## 2. The contract is now a two-repo release step

`scripts/export_contract.py` writes `docs/consult-contract.json`. The frontend
keeps its own committed copy and its `contract.test.ts` checks the TypeScript
against it. So changing the response shape is a coordinated release: regenerate
here, then open a PR there. Neither side can move it alone without the other's
tests going red — that is the point, not friction to route around.

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

- **Ayurvedic medicine names** — deferred by decision, not oversight. Notes
  currently name no medicine. When this happens it is Ayurvedic medicines only,
  and it needs the safety rules revisited first: `SYSTEM_RULES` rule 2 explicitly
  forbids naming one, so the content change and the prompt change must land
  together or the model will refuse to read its own corpus aloud.
- `scripts/ingest_knowledge.py` still targets one collection. Fine with one bot;
  it is the blocker on ever ingesting a second.

## Notes

- The 29 knowledge notes here are the source of truth. `library.json` is generated
  from them and committed into the frontend repo — edit the notes, never the JSON.
- **Removed from this roadmap:** "verify `deploy/setup.sh` on a clean VM". That
  directory was deleted in `3caf060` (10 Aug) and exists in neither repo, so the
  item had been asking for a check on a file that was already gone.
