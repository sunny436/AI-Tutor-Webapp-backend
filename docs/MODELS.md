# Models — what runs where, and why

> **Switched to free-only.** Every paid model was removed. Verify at any time
> with `python scripts/verify_free_only.py` — it reads the live config, prices
> each model against OpenRouter's catalogue, and exits 1 if anything is billable.
> Selection evidence: `python scripts/eval_free_models.py`.

## Before → after

| role | was (paid) | $/M | now (free) | $/M |
|---|---|---|---|---|
| Responder | `google/gemini-2.5-flash` | 0.30 / 2.50 | `nvidia/nemotron-3-nano-30b-a3b:free` | **0 / 0** |
| Router | `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | `nvidia/nemotron-3-nano-30b-a3b:free` | **0 / 0** |
| Fallback 1 | `deepseek/deepseek-v3.2` | 0.27 / 0.40 | `google/gemma-4-26b-a4b-it:free` | **0 / 0** |
| Fallback 2 | `qwen/qwen3.5-plus-02-15` | 0.26 / 1.56 | `nvidia/nemotron-3-super-120b-a12b:free` | **0 / 0** |
| Speech → text | `nemotron-omni:free` + paid fallback | 0 / 0.30 | `nemotron-omni:free` only | **0 / 0** |
| Text → speech | `openai/gpt-audio-mini` | 0.60 / 2.40 | **browser `speechSynthesis`** | **0 / 0** |
| Embeddings | `BAAI/bge-m3` | local | unchanged | local |

Cost per turn went from ~$0.003 to **$0**.

### Why these four, measured

`scripts/eval_free_models.py` scores every free chat model on the four things
that actually break this product. Full results:

| model | score | avg | why not |
|---|---|---|---|
| `nvidia/nemotron-3-nano-30b-a3b:free` | **4/4** | **4.6s** | chosen — also the fastest |
| `google/gemma-4-26b-a4b-it:free` | 4/4 | 16.0s | fallback 1 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 4/4 | 18.7s | fallback 2 |
| `nvidia/nemotron-nano-9b-v2:free` | 3/4 | 10.8s | returned an empty string for router JSON |
| `openrouter/free` | 3/4 | 15.1s | **0/4 headings** — would render a blank answer |
| `openai/gpt-oss-20b:free` | 3/4 | 20.2s | rate-limited mid-run |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 3/4 | 33.4s | named "antacid" — a safety-rule breach |
| `google/gemma-4-31b-it:free` | 0/4 | — | 429 on every single call |

The winner being the fastest settles the usual quality-vs-latency argument —
there was nothing to trade.

### What got worse, honestly

- **Text-to-speech sounds worse.** No free model emits speech — of 400 models,
  four output audio: two are paid, two (`google/lyria-*`) generate music. So the
  Listen button uses the **browser's own engine** (`window.speechSynthesis`)
  instead. Free, no key, works offline, starts instantly with no round trip —
  but it is a system voice, not a neural one. Set `TTS_MODEL=openai/gpt-audio-mini`
  in `.env` to get the better voice back at ~$0.005 per answer; the button
  prefers the backend whenever it answers and only falls back to the browser on
  a 503.
- **Two vendors in the chain, not three.** Only NVIDIA and Google ship free
  models that pass all four tests. Rate limits are survivable; a full NVIDIA
  outage leaves one option instead of two.
- **Free tiers rate-limit, and the retry logic had to be taught their wording.**
  A free-tier refusal reads *"…:free is temporarily rate-limited upstream"* —
  which contains none of the markers `_classify` originally looked for (no "per
  minute", no "tpm", no "503"). It was therefore classified **fatal**, so
  `invoke` re-raised immediately: no wait, no retry, and no move down the chain.
  The fallback existed but was unreachable for the single most common failure a
  free tier has.

  It did not look like a dropped request. It looked like bad answers: the first
  turn of a conversation came back empty, so a later "in Hindi" had no previous
  answer to translate and fell through to the off-topic refusal. Easy to blame
  on model quality. `_TRANSIENT` now carries `429`, `rate-limited`, `temporarily`
  and `capacity`; daily limits are still `exhausted` (waiting never clears them)
  and a bad key is still `fatal` (every model would reject it identically).
- **A key is still required.** "Free" means $0 per token, not "no account".

---

Every model this system uses, what it is for, and what it was chosen over. If you
are about to change one of these, the "why" column is the argument you need to
beat.

**One credential.** Everything below except the embedder runs on the single
OpenRouter key in `backend-python/.env`. There is one secret to rotate, one bill
to read, and one dashboard showing per-model spend. The embedder runs locally and
costs nothing.

---

## At a glance

| # | Model | Role | Selected by | $/M in | $/M out |
|---|---|---|---|---|---|
| 1 | `google/gemini-2.5-flash` | Responder | `config.PRIMARY_MODEL` | 0.30 | 2.50 |
| 2 | `google/gemini-2.5-flash-lite` | Router | `config.ROUTER_MODEL` | 0.10 | 0.40 |
| 3 | `deepseek/deepseek-v3.2` | Fallback 1 | `config.MODEL_CHAIN[1]` | 0.28 | 0.42 |
| 4 | `qwen/qwen3.5-plus-02-15` | Fallback 2 | `config.MODEL_CHAIN[2]` | ~0.40 | ~1.20 |
| 5 | `BAAI/bge-m3` | Embeddings | `config.EMBEDDING_MODEL` | local | local |
| 6 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Speech → text | `config.STT_MODEL_CHAIN[0]` | 0 | 0 |
| 7 | `google/gemini-3.5-flash-lite` | Speech → text fallback | `config.STT_MODEL_CHAIN[1]` | 0.30 | 2.50 |
| 8 | `openai/gpt-audio-mini` | Text → speech | `config.TTS_MODEL` | 0.60 | 2.40 |

---

## 1. Responder — `google/gemini-2.5-flash`

**Does:** every user-visible sentence. Consultation plans, knowledge answers,
follow-ups ("explain that in English"), conversational replies, and the
supportive-care reply for serious conditions.

**Called from:** `src/consult/responder.py` — `write_plan`, `write_knowledge`,
`rework_answer`, `write_supportive_care`.

**Why it won.** A bake-off (`scripts/eval_models.py`) scored candidates on the
things that actually break this product: emitting the exact section headings the
UI colour-matches, mirroring the user's language, and never naming a medicine.

| model | score | note |
|---|---|---|
| `google/gemini-2.5-flash` | **10/10** | chosen |
| `deepseek/deepseek-v3.2` | 9/10 | slower |
| `anthropic/claude-*` | — | rewrote the section headings, which breaks rendering |
| `openai/gpt-5-mini` | — | could not emit JSON under a token cap |

The heading failure is not cosmetic: `AnswerSections` matches heading strings
character for character and renders nothing it cannot match, so a model that
"improves" a heading produces a blank answer.

**If it fails:** `MODEL_CHAIN` takes over (#3, then #4).

---

## 2. Router — `google/gemini-2.5-flash-lite`

**Does:** classifies each incoming message — greeting, health complaint,
follow-up, off-topic, aside — and generates the intake questions.

**Called from:** `src/consult/router.py`, `src/consult/planner.py`.

**Why it won.** Router latency is the only latency the user feels as *dead time*:
nothing happens on a turn until it returns. It was chosen on speed, not quality.

| model | correct | latency |
|---|---|---|
| `google/gemini-2.5-flash-lite` | 2/2 | **4.9s** — chosen |
| `mistralai/mistral-small-3.2-24b` | 2/2 | 12.1s |
| `qwen/qwen3.7-flash` | 0/2 | spends its token cap on reasoning |
| `openai/gpt-5-nano` | 0/2 | same |

The two zero-scorers fail the same way and it is worth knowing: given a small
`max_tokens`, a reasoning model spends the whole budget thinking and emits no
JSON at all. `MAX_TOKENS_ROUTER` is a spend guard, so the model has to work
inside it.

**Pinned, deliberately.** `invoke(model=...)` disables the fallback chain for
router calls — the router wants the cheap fast model, not the best one.

---

## 3. Fallback 1 — `deepseek/deepseek-v3.2`

**Why it is second and not first:** it scored 9/10 against the responder's 10/10,
and it is slower.

**Why it is on the list at all:** it is a *different vendor*. A chain of three
Google models survives a quota exhaustion but not a Google outage. This is the
entry that makes the chain meaningful.

---

## 4. Fallback 2 — `qwen/qwen3.5-plus-02-15`

Last resort, and a third vendor. Strong Hindi and Devanagari handling, which
matters because the fallback path must not silently degrade the language quality
for exactly the users most likely to be writing in Hindi.

**How the chain actually behaves** (`src/llm.py`, `invoke`):

- *per-minute* limit (`tpm`, `rpm`, 503) → wait and retry the **same** model, up
  to `MAX_ATTEMPTS = 3`, honouring the "try again in Ns" hint.
- *per-day* limit (`tpd`, quota) → put that model on a `COOLDOWN_SECONDS = 900`
  cooldown and move to the next one.
- *fatal* (bad key, malformed request) → raise immediately. Working down the
  chain would fail identically on every model and only waste time.

That distinction is the whole point: a per-minute limit means "wait", a per-day
limit means "this model is done for now". Treating them the same either burns the
chain on a hiccup or hammers a dead model.

---

## 5. Embeddings — `BAAI/bge-m3`

**Does:** vectorises the Ayurveda/Yoga notes AND every uploaded user document.

**Runs locally** via `sentence-transformers`. No API call, no cost, no key.

**Why it won.** Measured with `scripts/eval_embeddings.py` on the queries this app
actually gets — Devanagari, Hinglish, and English asking about the same thing.

| model | multilingual | note |
|---|---|---|
| `BAAI/bge-m3` | **yes** | chosen |
| `sentence-transformers/all-MiniLM-L6-v2` | no | the old default; English-only, so a Hindi query matched nothing |

**Two settings that are not optional:**

- `normalize_embeddings=True`. Without it, vectors keep their raw magnitude and
  Chroma returns relevance scores like **−17** for the correct chunk, which no
  threshold can be set against.
- `collection_metadata={"hnsw:space": "cosine"}`. Chroma defaults to L2. Cosine is
  what these embeddings are trained for and what makes `relevance = 1 - distance`
  a real 0..1 number. **Only read when the collection is created** — changing it
  means wiping the store and re-ingesting.

Both apply to `user_documents` too, and for the same reasons.

---

## 6 & 7. Speech → text — `nemotron-3-nano-omni:free`, then `gemini-3.5-flash-lite`

**Does:** turns a recorded clip into text *and reports which language was spoken*.

**Called from:** `src/llm.py` → `transcribe`, exposed as `POST /transcribe`.

**Why a multimodal chat model instead of a dedicated speech service.** A
transcription endpoint returns words. These return words **plus the detected
language**, which is written straight into the conversation's sticky
`context.language`. That is the entire reason somebody who speaks Hindi gets a
Hindi answer without having to ask for one. A words-only service would need a
second language-detection step over a transcript that has already lost the accent.

They also handle Hinglish code-switching — "mujhe acidity hai since 2 weeks" — in
one pass, which is how people actually talk here.

**Why a chain.** The free tier is the right default and is also the first thing to
rate-limit. The paid model stands behind it. Both were verified to accept audio
input against the live OpenRouter catalogue.

**Format constraint.** The API accepts `wav` and `mp3`. `MediaRecorder` produces
`webm/opus` on Chrome and `mp4/aac` on Safari — neither is accepted. So
`lib/consult/use-voice.ts` decodes the clip with the Web Audio API and re-encodes
it as 16 kHz mono 16-bit WAV in the browser. No ffmpeg, no server transcode, and
identical bytes from every browser.

---

## 8. Text → speech — `openai/gpt-audio-mini`

**Does:** reads an answer aloud when the user presses **Listen**.

**Called from:** `src/llm.py` → `speak`, exposed as `POST /speak`.

**Why the mini and not `openai/gpt-audio`:** four times cheaper (0.60/2.40 against
2.50/10.00) for a job that is reading prose aloud. The full model is available by
setting `TTS_MODEL` if the voice quality is ever judged insufficient.

**Two hard API constraints, both found by being rejected — do not "simplify" these
away:**

1. `stream: true` is mandatory. A non-streaming audio request is refused outright
   with *"Audio output requires stream: true"*.
2. Once streaming, the **only** accepted format is `pcm16`. `mp3`, `wav` and
   `opus` are each refused with *"does not support ... when stream=true"*.

So the response arrives as headerless 24 kHz mono PCM across SSE events, and
`_wav_container()` puts a RIFF header on it before returning — a browser `<audio>`
element cannot play raw PCM. The 24 kHz figure appears nowhere in the response;
get it wrong and playback is chipmunked or slowed.

Each SSE fragment is base64-decoded **separately**. Concatenating the base64 text
and decoding once would truncate at the first fragment carrying `=` padding.

**On demand, never autoplay.** Plans run past 1,500 characters. Autoplay would be
obnoxious and would make cost unpredictable, since speech is billed per output
token whether anyone listens or not. The clip is cached per message, so replaying
is free.

---

## Cost per turn

| turn type | cost |
|---|---|
| text question → text answer | ~$0.003 |
| voice question (free STT) → text answer | ~$0.003 |
| voice question (paid STT) → text answer | ~$0.004 |
| any answer, read aloud | +~$0.005 |

Voice roughly doubles the cost of a turn that uses it. Embedding is free.

## Spend guards

`MAX_TOKENS_ROUTER` / `_PLANNER` / `_ANSWER` in `config.py` cap each call. On a
metered account these are not formatting preferences: a model that fails to stop
is billed for everything it emits.
