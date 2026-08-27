# Models — what runs where, and why

**Verified on production 2026-08-27 by recording the actual outbound calls**, not
by reading config. Method is at the bottom; it matters, because two of the three
instrumentation layers silently missed calls and would have produced a confident
wrong answer.

## The whole inventory

| # | Model | Job | Provider | Selected by |
|---|---|---|---|---|
| 1 | `gemini-3.1-flash-lite` | Router — classifies every message | Ollima | `config.ROUTER_MODEL` |
| 2 | `gemini-3.1-flash-lite` | Chat, intake questions, gathering | Ollima | `config.PRIMARY_MODEL` |
| 3 | `gemini-3.5-flash-low` | Chain fallback for 1 and 2 | Ollima | `config.MODEL_CHAIN[1]` |
| 4 | `baai/bge-m3` | Embeddings — uploaded medical reports | OpenRouter | `config.EMBEDDING_MODEL` |
| 5 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Speech → text | OpenRouter | `config.STT_MODEL_CHAIN[0]` |
| 6 | **unnamed** | **Writes the health answer / plan** | **GraphRAG vendor** | **not selectable — see below** |
| — | *(none)* | Text → speech | off | `config.TTS_MODEL` empty |

Two hosts, and only two, are contacted by this backend for AI:
`api.ollima.com` and `openrouter.ai` — plus `graphrag.internal` for #6.

## #6 is the one that surprises people

The text a user actually reads as their Ayurveda plan is **not written by any
model this repo selects**. `consult/graph.py:382` calls `graphrag.answer(query)`
and returns the vendor's prose verbatim. The comment at `graph.py:936` states it
plainly: *"GRAPHRAG WRITES THE PLAN NOW, not our own model."*

`_answer_request` (`retrieval/graphrag.py`) sends `query`, `k` and
`document_ids` — **no `model` field** — so the vendor picks the model and does
not disclose it. Measured: a plan request returns 700–1200 characters of
generated prose, language-matched to the question.

`GRAPHRAG_ENABLED` does **not** gate this. That flag gates only the retriever in
`retrieval/registry.py`. The only gate on `/v1/answer` is whether
`GRAPHRAG_BASE_URL` and `GRAPHRAG_API_KEY` are set — and on production they are.

This is why `safety.scan` and the gathering red-flag check run **before** that
call. The vendor's prompt cannot be given a rule, a persona or an output format,
so everything this product is accountable for has to sit outside it.

## Why these Ollima models

Measured on the VM with `scripts/eval_chain_models.py`, against the router and
intake calls that decide whether a consultation happens at all:

| Model | Router | Intake questions | Time |
|---|---|---|---|
| `gemini-3.1-flash-lite` | ok | 4 | **6.5s** ← primary + router |
| `gemini-3.5-flash-low` | ok | 4 | 9.3s ← fallback |
| `gpt-oss-120b` | ok | 6 | 21.9s |
| `deepseek-v4-flash` | ok | 6 | 47.9s |
| `gemma4` | — | — | 502 on every call |

The two rejects are the useful part. `deepseek-v4-flash` reads like the obvious
primary from its name and is the worst usable option here: it is a reasoning
model — 129 completion tokens for "say ok" under a `max_tokens` of 5 — and takes
48s for a job the chosen model does in 6.5. Six intake questions instead of four
is not worth seven times the wait in a product whose actual complaint is
slowness. `gpt-oss-120b` is the same trade, milder, and is the one to promote if
4 questions ever proves too thin.

Against the OpenRouter chain this replaced, on the same four-turn conversation:

| | OpenRouter (before) | Ollima (now) |
|---|---|---|
| Turn latency | 17.4s / 10.8s / 27.2s / 24.9s | **9.6s / 3.5s / 4.5s / 3.8s** |
| Router | **failing every turn** — "length limit reached" after 836 reasoning tokens | works |

## There is no cross-provider fallback

By instruction. OpenRouter is not a backstop for chat; it serves embeddings and
speech and nothing else. **When Ollima is unavailable this product cannot
answer.**

That is not hypothetical. On 2026-08-27 every Ollima chat call returned
`401 TensorZero authentication error: Database error: pool timed out` after
hanging for the full timeout, and recovered minutes later. The failure was
account-wide and identical across every model — which is why the chain is two
entries and not five. Each dead entry costs another `LLM_TIMEOUT_SECONDS` before
the user is told it failed, and none of them would have answered.

## Embeddings moved off this machine

`baai/bge-m3` used to be downloaded and held in memory: 1.9 GB on a 3.8 GB host,
loaded before the first answer could be given. It is now the same model over
OpenRouter.

The swap is **exact**, which is the only reason it was safe: 1024 dimensions and
unit norm on both sides, and the cosine between a local vector and a remote
vector for the same text is **1.0000**. So `MIN_RELEVANCE` stays calibrated,
vectors already written to Chroma stay readable, and nothing had to be
re-ingested.

The cost, stated plainly: text from uploaded medical reports now leaves this
host.

## Speech-to-text stays on OpenRouter — a constraint, not a preference

Ollima serves no speech model. `/v1/audio/transcriptions` returns 404 and its
catalogue lists nothing that accepts audio, so there is nowhere to move it.
Re-check when their catalogue grows; until then the mic button needs OpenRouter
or it needs to be off.

Text-to-speech is off entirely. `TTS_MODEL` is empty, so `TTS_ENABLED` is false
and `server.py` returns 503 before `speak()` is reached — the Listen button
reports unavailable rather than quietly spending money.

## Known problems, as of 2026-08-27

- **The mic button is broken.** Speech-to-text returns `402 Payment Required`.
  The model is fine — it answers a text prompt with HTTP 200 — the OpenRouter
  balance is not: $19.83 of $20 spent, ~$0.17 left. Embeddings still work but
  run on the same balance, so uploaded reports go next.
- **GraphRAG abstains on most questions.** Its corpus no longer contains this
  project's 29 notes; it holds Sanskrit source PDFs. The coverage check measures
  around 0.09 against a 0.65 floor, so the assistant says it has no information
  rather than answering. Vendor-side; not fixable from this repo.

## How this was verified, and why the method matters

Config was not trusted. The production process was instrumented at three
independent layers while a real consultation ran:

1. `socket.getaddrinfo` — every host resolved. Library-agnostic: nothing reaches
   the network without it.
2. The OpenAI SDK's `_base_client.post` and langchain's `BaseChatOpenAI._generate`
   — the `model` argument, taken from the call itself.
3. `httpx.HTTPTransport.handle_request` — raw httpx calls.

Layer 3 caught **only** speech-to-text; the OpenAI SDK bypasses it entirely, and
an earlier attempt patching `httpx.Client.send` missed just as much. Stopping at
either would have reported "only speech-to-text runs", which is wrong. Layer 1 is
the one to trust; layer 2 is what supplies model names.

Re-run it before believing any of the above has stayed true.
