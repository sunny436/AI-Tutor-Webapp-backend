"""
knowledge.py
------------
Ayurveda/Yoga knowledge search (the "RAG" part), with CACHING for speed.

IMPORTANT (performance): the embedding model and the vector database are loaded
ONCE and reused for every request. Earlier they were re-loaded on every message,
which made each answer very slow. Now the first request warms them up and the
rest are fast.

`langchain_openai` is imported HERE, at module level, not lazily inside
`get_embeddings()` (where it used to live). Measured: `import langchain_openai`
alone costs ~13s the first time it happens in a process — almost certainly
pydantic building the core validation schema for its model classes — and
`OpenAIEmbeddings()` construction itself is fast (~1-2s) once that import has
already paid its cost. A lazy import defers that 13s to the first real call
into this module instead of to server startup, where `warm_up()` (server.py)
is supposed to absorb it — and `warm_up()` swallows every exception silently,
so a lazy import failing there would leave the cost sitting in wait for
whichever real request happens to be first. Importing eagerly, alongside
chromadb and langchain_chroma right below (which already load this way), means
the cost lands at process-import time, before `warm_up()` even runs, not
inside any request.
"""

import itertools
import re
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
import config
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

# The one collection this backend has. It was derived from a bot registry when
# the backend was meant to host several chatbots; there is one Ayurveda chatbot,
# and the vendor now isolates GraphRAG per API key rather than per project id,
# so the registry bought nothing and cost a parameter on 72 call sites.
DEFAULT_COLLECTION_NAME = "ayurveda_yoga"

# Back-compat alias. Nothing in this repo imports it, but it was the public name
# for a long time and removing it buys nothing.
COLLECTION_NAME = DEFAULT_COLLECTION_NAME


def _resolve(collection: str | None) -> str:
    return collection or DEFAULT_COLLECTION_NAME

# Words that carry no topic signal. Without these, "mujhe acidity hai" and
# "gas ki problem" both match every note that happens to use the same filler.
# Short particles matter as much as long ones here, because tokens are kept down
# to two characters — "sar", "gas" and "pet" are the whole signal in a lot of
# Hinglish questions, and a length cut-off that loses them loses the question.
_STOPWORDS = {
    # Hinglish particles and fillers
    "ka", "ki", "ke", "ko", "se", "me", "mein", "ma", "hi", "bhi", "or", "aur",
    "ek", "do", "ye", "yeh", "wo", "woh", "is", "us", "na", "to", "toh", "ab",
    "jo", "kar", "kya", "kyun", "kaise", "mujhe", "mujha", "mera", "meri",
    "mere", "hai", "hain", "ha", "raha", "rahi", "rahe", "hota", "hoti", "hote",
    "karna", "karta", "karte", "liye", "wala", "wali", "bahut", "thoda",
    "jaisa", "nahi", "koi", "gaya", "gayi", "batao", "bataye", "chahiye",
    # domain filler — present in every note, so it discriminates nothing
    "problem", "upay", "ilaj", "ilaaj", "treatment", "ayurveda", "ayurvedic",
    "yoga", "diet", "ke liye",
    # English filler
    "a", "i", "of", "in", "on", "at", "it", "be", "an", "the", "and", "for",
    "my", "me", "is", "are", "what", "with", "from", "this", "that", "have",
    "there", "your", "some", "help", "tell", "does", "please", "about", "how",
    "can", "you", "get", "why", "when", "any", "best", "good",
}


# Hindi-script filler, so a Devanagari query is trimmed the same way a romanised
# one is. Separate set because these never collide with the Latin ones.
_STOPWORDS |= {
    "का", "की", "के", "को", "से", "में", "मे", "है", "हैं", "हूँ", "हूं", "और",
    "या", "यह", "वह", "इस", "उस", "ना", "नहीं", "कोई", "क्या", "कैसे", "क्यों",
    "मुझे", "मेरा", "मेरी", "मेरे", "रहा", "रही", "रहे", "हो", "होता", "होती",
    "करना", "करता", "लिए", "बहुत", "थोड़ा", "बताओ", "चाहिए", "उपाय", "इलाज",
    "समस्या", "आयुर्वेद", "योग",
}


# Latin letters, digits, and the Devanagari block minus its two danda marks
# (U+0964 ।, U+0965 ॥), which are sentence punctuation rather than letters.
#
# Spelling the block out is not paranoia. The obvious `\W+` with re.UNICODE is
# WRONG here: Python's `\w` follows `str.isalnum()`, and Devanagari vowel signs
# (ी, ू, ा) are combining marks, which are not alphanumeric. `\W+` therefore
# splits ON the matras and shreds every Hindi word into consonant fragments —
# "रूसी" became ['र', 'स'], "नींद" became ['न', 'द']. Those fragments collide
# across every note in the corpus, so "रूसी की समस्या" matched `insomnia.md`.
_WORD_SPLIT = re.compile(r"[^0-9a-zऀ-ॣ०-ॿ]+")


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens, minus filler.

    Handles Latin and Devanagari. The previous ASCII-only `[^a-z0-9]+` deleted
    every Devanagari character outright, so a Hindi query produced zero tokens
    and the topic index could not see it at all: "बवासीर की समस्या" scored
    nothing here and fell through to vector search, where `piles.md` sat at
    0.514 — just under the threshold — leaving the user with no notes for a
    condition the corpus covers in full.
    """
    return [
        token
        for token in _WORD_SPLIT.split((text or "").lower())
        if token and token not in _STOPWORDS
    ]

# Module-level caches (loaded once, reused forever).
#
# The embedding CLIENT is shared across collections on purpose — it is a thin
# HTTP client now, and carries no per-collection state. The vector STORES are keyed by collection,
# which is what keeps uploaded reports out of the shared notes.
_embeddings = None
_vector_stores: dict[str, Chroma] = {}

# ONE chromadb client for the whole process, shared by every collection at this
# persist_directory (the notes here, uploaded reports in user_documents.py).
#
# Not sharing this was a real bug, not a style choice. Each `Chroma(persist_
# directory=...)` call used to mint its OWN `chromadb.PersistentClient`, and
# chromadb keys a per-path "system" (the Rust engine underneath) by that exact
# path in a class-level registry — chromadb/api/shared_system_client.py,
# `_create_system_if_not_exists`. Two client objects for the same path share
# ONE system, and building it is a several-step, unlocked sequence (create,
# register in the class dict, THEN start()). Two `asyncio.to_thread` calls
# racing to construct their own client for the same path — exactly what the
# retrieval pipeline's concurrent gather does on the first request, one thread
# for this file's notes and one for user_documents.py's reports — could
# interleave: the second thread saw the system already registered and used it
# before the first thread's `.start()` had actually run, and hit
# `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`
# (chromadb/api/rust.py — `bindings` is set inside `start()`, nowhere else).
# Measured: reproduced on the first concurrent access after a fresh ingest,
# gone once a single shared client removes the second registration entirely.
#
# The lock guards this cache the same way — two threads racing past `is None`
# would just reintroduce the identical bug one level up.
_chroma_client: chromadb.ClientAPI | None = None
_chroma_client_lock = threading.Lock()


def get_chroma_client() -> chromadb.ClientAPI:
    """The one chromadb client every collection at VECTOR_DB_DIR is opened through."""
    global _chroma_client
    if _chroma_client is None:
        with _chroma_client_lock:
            if _chroma_client is None:
                _chroma_client = chromadb.PersistentClient(path=config.VECTOR_DB_DIR)
    return _chroma_client


class _PooledEmbeddings(Embeddings):
    """Round-robins embed calls across a small pool of independent clients.

    WHY THIS EXISTS, NOT JUST ONE CLIENT. `Chroma` caches whatever
    `embedding_function` object it is given for the life of the vector store
    (`get_vector_store` below caches the `Chroma` instance itself, per
    collection) — so returning a fresh `OpenAIEmbeddings` per call from
    `get_embeddings()` would not help; every search against an already-open
    store keeps calling `.embed_query()` on the ONE object it was built with.
    The pooling has to live INSIDE that one long-lived object instead.

    MEASURED, NOT ASSUMED. One shared `OpenAIEmbeddings` (one underlying
    `httpx`/`httpcore` connection pool) serializes CONCURRENT calls somewhere
    in new-connection establishment: 6 concurrent `embed_query` calls through
    one shared client took 13.46s total locally / 7.00s on the production VM,
    even though every individual call completed in under a second once it
    actually started — confirmed by isolating the network entirely (6
    concurrent calls with 6 separate plain `httpx.Client`s: 0.97s total) and
    by isolating the SDK client specifically (6 concurrent calls with 6
    freshly-built `openai.OpenAI` clients: 3.00s total). A small pool of
    independent clients, round-robined, gets the same result — measured 1.18s
    for the same 6 concurrent calls across a 4-client pool — while each
    individual client still keeps its own keep-alive connection warm for
    ordinary, non-concurrent, sequential traffic (the common case).

    This is exactly what was causing the intermittent local-knowledge-
    retriever timeouts under concurrent GraphRAG load: GraphRAG's own HTTP
    call doesn't block the embeddings call directly (different host,
    different client) — simply having MORE THAN ONE embedding call in flight
    at once (which concurrent GraphRAG+knowledge retrieval, or more than one
    user's turn overlapping, both produce) was enough to trigger this.
    """

    def __init__(self, size: int) -> None:
        self._clients = [_build_openai_embeddings() for _ in range(max(1, size))]
        # A plain, unlocked counter. A rare race landing two concurrent calls
        # on the same pool member just means slightly uneven distribution
        # that turn, not a correctness problem — not worth a lock for a
        # best-effort load spread.
        self._counter = itertools.count()

    def _client(self):
        return self._clients[next(self._counter) % len(self._clients)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client().embed_query(text)


def _build_openai_embeddings():
    """One real embeddings client. See `_PooledEmbeddings` for why several of
    these, not one, are what `get_embeddings()` actually hands out.

    OPENROUTER, NOT THIS MACHINE. bge-m3 used to be downloaded and held in
    memory here — 1.9 GB on a 3.8 GB host, loaded before the first answer could
    be given. It is now the same model called over the same OpenRouter key as
    everything else.

    The swap is exact, measured rather than assumed: 1024 dimensions both sides,
    both unit-normalised, and the cosine between a local and a remote vector for
    the same text is 1.0000. That matters because `MIN_RELEVANCE` is calibrated
    per embedding model and vectors already stored in Chroma were written by the
    local one — both stay valid, and nothing has to be re-ingested.

    `check_embedding_ctx_length=False` because that pre-check tokenises with
    tiktoken, which is OpenAI's tokeniser and not bge-m3's. Letting it run would
    have it split text on the wrong boundaries for a model it does not describe.

    `request_timeout=config.KNOWLEDGE_EMBED_TIMEOUT_S` IS LOAD-BEARING, not a
    tuning knob. Leaving it unset does not mean "use the SDK's own sane
    default" - langchain_openai defaults this field to None, and the openai
    SDK treats an explicit `timeout=None` as "no timeout at all", not "use
    mine". A stalled or slow OpenRouter response then blocks this call's
    worker thread indefinitely, and the pipeline's own RETRIEVAL_TIMEOUT_S
    cannot stop it - `asyncio.wait_for` only abandons the asyncio-side await,
    it does not kill the thread. See KNOWLEDGE_EMBED_TIMEOUT_S in config.py
    for how this was confirmed and reproduced.

    `max_retries=1`, down from the openai SDK's own default of 2, for the
    same reason. The SDK retries with exponential backoff BETWEEN each
    attempt, so a genuinely slow call hitting the timeout above 2-3 times in
    a row (its default) can cost far MORE than the timeout implies - measured
    up to ~18s total for one embed call, comfortably past this pipeline's own
    RETRIEVAL_TIMEOUT_S (8.0), which then abandons the await while the SDK
    keeps retrying underneath it, still on the orphaned thread. `pipeline.py`
    already treats one retriever failing as "degrade gracefully, don't fail
    the consultation" (`_safe_retrieve`, and `search_knowledge_scored`'s own
    `except Exception: return []`), so retrying heavily INSIDE one embed call
    only works against that existing design - one retry is enough headroom
    for a genuine one-off blip while keeping the realistic worst case
    (timeout + backoff + retry) safely under RETRIEVAL_TIMEOUT_S.
    """
    return OpenAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        check_embedding_ctx_length=False,
        request_timeout=config.KNOWLEDGE_EMBED_TIMEOUT_S,
        max_retries=1,
    )


def get_embeddings():
    """The embedding client, built once and reused.

    Actually a small pool of clients behind one object — see
    `_PooledEmbeddings`. Everything that held for "one client, cached and
    reused" before still holds: this function still returns the SAME object
    every time, callers are unaffected, and nothing has to change anywhere
    else.
    """
    global _embeddings
    if _embeddings is None:
        _embeddings = _PooledEmbeddings(config.KNOWLEDGE_EMBED_POOL_SIZE)
    return _embeddings


def get_vector_store(collection: str | None = None) -> Chroma:
    """Open the vector DB once and reuse it.

    Still cached per collection name, because `user_documents` is a second,
    genuinely separate store - uploaded medical reports must never be searchable
    alongside the shared notes.
    """
    name = _resolve(collection)
    store = _vector_stores.get(name)
    if store is None:
        store = Chroma(
            collection_name=name,
            embedding_function=get_embeddings(),
            client=get_chroma_client(),
            # Chroma defaults to L2. Cosine is what these sentence embeddings are
            # trained for, and it is what makes `relevance = 1 - distance` a
            # meaningful 0..1 number. Only read at collection creation time, so
            # changing it means wiping the store and re-ingesting.
            collection_metadata={"hnsw:space": "cosine"},
        )
        _vector_stores[name] = store
    return store


def warm_up(collection: str | None = None) -> None:
    """Called at server startup so the first real answer is already fast."""
    try:
        get_vector_store(collection).similarity_search("warm up", k=1)
        get_topic_index(collection)
    except Exception:
        pass


# --- topic index ------------------------------------------------------------
# Built once from the `topic`/`aliases` front matter that ingest stored on every
# chunk. This is what makes retrieval work for Hinglish, which the embedding
# model handles unreliably: measured on this corpus, "pet phoolna" and "baal
# jhad rahe hain" did not return the right note anywhere in the top 12, even
# though both phrases are listed verbatim in that note's aliases. A keyword the
# author explicitly wrote down should never lose to a similarity score.
# PER COLLECTION, and this half matters as much as the vector store above.
#
# The topic index is built from the notes' own front matter, so a single shared
# index would hand `match_topics` a list of AYURVEDA filenames no matter which
# bot asked — and the retriever then searches those sources by name, bypassing
# the score threshold entirely. Isolating the store but not the index would look
# correct and leak anyway.
@dataclass
class _TopicIndex:
    """One collection's alias index: the three views `match_topics` needs."""

    tokens: dict[str, set[str]] = field(default_factory=dict)
    phrases: dict[str, list[list[str]]] = field(default_factory=dict)
    token_df: dict[str, int] = field(default_factory=dict)


_topic_indexes: dict[str, _TopicIndex] = {}

# Tier 2 only. A token appearing in more notes than this is filler that happened
# to land inside a longer alias phrase — "kaam" from "kisi kaam mein mann nahi
# lagta", "time" from "period time par nahi aata" — and proves nothing on its own.
MAX_DISTINCTIVE_DF = 2
# Enough weight to claim a topic in tier 2. One distinctive token reaches it; two
# ordinary ones do too; a single common word never does.
#
# RAISED 1.0 -> 1.5. At 1.0 two PREFIX-ONLY matches (0.5 each) were enough, and a
# tier-2 claim skips the relevance floor entirely in retrieval/knowledge.py - so a
# claim built from nothing but prefixes reached the prompt under the heading
# "Trusted Ayurveda / Yoga knowledge" with no score check at all. Observed on a
# real message from the logs:
#
#     "matlab ya na oily ka ka bad jayaf hotie ha"
#         -> claimed immunity + weight-loss on prefixes alone
#         -> served 4 chunks at best score 0.474, under the 0.52 floor
#
# 1.5 means a claim now needs at least one EXACT token match; prefixes can top it
# up but can no longer carry it alone. Measured over a 14-query sweep of typo-heavy
# Hinglish: all 12 good claims survive unchanged, and that one bad claim is the
# only thing that disappears. It is this surgical because tier 1 (phrase matching)
# is what actually serves the healthy queries; this gate only guards tier 2.
#
# Measure any future change with the real `match_topics`. A tier-2-only
# reimplementation of this exact change reported "6 of 11 claims lost" - the
# opposite conclusion - because it skipped tier 1 entirely.
MIN_TOKEN_SCORE = 1.5


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a `---` header off the top of a note, returning (fields, body).

    Deliberately not a YAML parser. The header only ever carries `topic` and
    `aliases`, and these notes are hand-written — a stray colon or an unquoted
    ampersand should not take down the whole index. Indented continuation lines
    are folded into the previous key so a long alias list can wrap, which most
    of the 29 notes do.

    This is the canonical copy. `scripts/ingest_knowledge.py` imports it rather
    than keeping its own, so the index and the ingest can never disagree about
    what a note's aliases are.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text

    fields: dict[str, str] = {}
    key = ""
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if line[:1].isspace() and key:
            fields[key] += " " + line.strip()  # wrapped continuation
        elif ":" in line:
            name, _, value = line.partition(":")
            key = name.strip().lower()
            fields[key] = value.strip()
    return fields, text[match.end() :]


def _get_index(collection: str | None = None) -> _TopicIndex:
    """Build (once) and return one collection's alias index.

    READS THE NOTES, NOT THE VECTOR STORE. This used to pull `topic`/`aliases`
    out of Chroma metadata, which made the alias index depend on an ingest
    having run — and `data/vector_store` is a gitignored build artifact, so a
    fresh host had the notes, no index, and no error anyone would notice.
    INFRASTRUCTURE.md §6 documents that trap; reading the front matter straight
    from `data/knowledge/*.md` removes it, and lets the embedding model go.

    Same two fields, same tokenisation, same `source` key (the bare filename) as
    the metadata carried, so this is a change of data source and nothing else.
    Anything that moves in the 74-query sweep is a regression, not an
    improvement.
    """
    name = _resolve(collection)
    cached = _topic_indexes.get(name)
    if cached is not None:
        return cached

    built = _TopicIndex()
    try:
        directory = Path(config.KNOWLEDGE_DIR)
        notes = sorted(directory.glob("*.md")) + sorted(directory.glob("*.txt"))
        for note in notes:
            source = note.name
            if source in built.tokens:
                continue
            fields, _ = parse_front_matter(note.read_text(encoding="utf-8"))
            topic = fields.get("topic", "")
            aliases = fields.get("aliases", "")
            if not topic and not aliases:
                # An unconverted note still answers, it just cannot be claimed
                # by name. Silent here would look identical to a healthy note.
                print(f"[knowledge] {source} has no topic/aliases front matter")
                continue
            built.tokens[source] = {
                t for t in _tokens(f"{topic} {aliases}") if len(t) >= 2
            }
            # The topic title counts as a phrase too — it is how a note names
            # itself, and it is often what the user types.
            phrases = [_tokens(part) for part in f"{topic},{aliases}".split(",")]
            built.phrases[source] = [p for p in phrases if p]
    except Exception as error:
        # DO NOT CACHE A FAILURE. This used to fall through and store the empty
        # index for the process lifetime, so one transient read error at startup
        # left `match_topics` returning nothing forever. Rarer now that it is a
        # directory read rather than a database call — a missing KNOWLEDGE_DIR
        # or an unreadable note is about all that reaches here — but the
        # consequence is unchanged, so the guard stays.
        #
        # That is now far worse than it was. GraphRAG's coverage gate and its
        # english_handle query expansion BOTH read this index, so an empty one
        # turns the product into a blanket refusal machine - and every other
        # signal, /health included, still reads green.
        print(
            f"[knowledge] could not build topic index for {name!r}: {error}. "
            "NOT caching the failure; the next call will retry."
        )
        return built

    for tokens in built.tokens.values():
        for token in tokens:
            built.token_df[token] = built.token_df.get(token, 0) + 1

    if not built.tokens:
        # An empty index that did not raise is still an outage - an empty or
        # missing KNOWLEDGE_DIR looks identical to a healthy one otherwise, and
        # this index is what picks the document GraphRAG is asked about.
        print(
            f"[knowledge] topic index for {name!r} is EMPTY "
            f"(read {config.KNOWLEDGE_DIR!r}); not caching it."
        )
        return built

    _topic_indexes[name] = built
    return built


def get_topic_index(collection: str | None = None) -> dict[str, set[str]]:
    """`{source filename: {searchable token, ...}}` from every note's front matter.

    The companion phrase view holds each `aliases:` entry as a whole phrase. Both
    are needed and they answer different questions: the token set is a bag of
    words, the phrase list preserves the fact that the author wrote "triphala" as
    a complete search term but "kaam" only ever as one word inside a sentence.
    """
    return _get_index(collection).tokens


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Does `needle` appear as a contiguous run inside `haystack`?"""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start] == first and haystack[start : start + len(needle)] == needle:
            return True
    return False


def match_topics(query: str, limit: int = 2, collection: str | None = None) -> list[str]:
    """Sources whose author-written aliases identify the query's topic.

    Two tiers, because one rule cannot serve both cases.

    TIER 1, PHRASES. The query contains a complete alias entry. This is the
    strong signal and it runs first: an alias is a search term the author
    deliberately wrote down, so containing one whole settles the topic. It is
    also what a bag-of-words score gets wrong — for "triphala kis kaam aata hai",
    counting tokens let `low-mood` win on "kaam" + "kis"~"kisi" while
    `common-herbs` lost with its single, decisive "triphala".

    TIER 2, WEIGHTED TOKENS. Only when no phrase matches, because users inflect:
    the note stores "baal jhadna" and the user types "baal jhad rahe hain".
    Tokens are weighted by how many notes claim them, so a rare word can carry a
    match alone while common ones must gang up. Without that weighting "bs kuch
    nahi kat rha ha time" claimed irregular-periods on "time" alone.
    """
    query_tokens = [t for t in _tokens(query) if len(t) >= 2]
    if not query_tokens:
        return []

    # Scoped to ONE collection, so a bot can only ever be handed its own notes'
    # filenames. The retriever searches by those names and skips the relevance
    # threshold when it does, so a cross-bot name here would be a direct leak.
    scoped = _get_index(collection)

    # --- tier 1: whole alias phrase present in the query ---------------------
    phrase_hits: list[tuple[int, str]] = []
    for source, phrases in scoped.phrases.items():
        longest = max(
            (len(p) for p in phrases if _contains(query_tokens, p)),
            default=0,
        )
        if longest:
            phrase_hits.append((longest, source))
    if phrase_hits:
        # Longest match wins: "period pain" beats a note claiming only "period".
        phrase_hits.sort(key=lambda row: (-row[0], row[1]))
        best = phrase_hits[0][0]
        return [source for length, source in phrase_hits[:limit] if length == best]

    # --- tier 2: weighted token overlap --------------------------------------
    scored: list[tuple[float, str]] = []
    for source, alias_tokens in scoped.tokens.items():
        score = 0.0
        for token in query_tokens:
            frequency = scoped.token_df.get(token, 0)
            if token in alias_tokens:
                # Rare tokens are worth a full match on their own; common ones
                # are worth a fraction, so several must agree.
                score += 1.0 if frequency <= MAX_DISTINCTIVE_DF else 0.34
            elif any(token.startswith(a) or a.startswith(token) for a in alias_tokens):
                # Prefix-only. Real for morphology ("jhad" -> "jhadna"), but also
                # how "under" once matched "underweight", so it never suffices alone.
                score += 0.5
        if score >= MIN_TOKEN_SCORE:
            scored.append((score, source))
    if not scored:
        return []

    scored.sort(key=lambda row: (-row[0], row[1]))
    best_score = scored[0][0]
    return [source for score, source in scored[:limit] if score == best_score]


def search_knowledge_scored(
    query: str,
    k: int = 4,
    sources: list[str] | None = None,
    collection: str | None = None,
) -> list[tuple]:
    """Top-k matching notes as (Document, relevance) pairs.

    Relevance runs 0..1, higher being closer. The score matters: a plain
    similarity search ALWAYS returns k results, so a question about migraine
    still comes back with the digestion and sleep notes just because they are the
    least-bad matches in a small corpus. Feeding those to the model as "trusted
    knowledge" is worse than feeding it nothing, because it will dutifully build
    an answer around them.

    Callers filter on the score so "the knowledge base has nothing on this" is a
    state we can actually detect, and fall back to the model's own knowledge.
    """
    try:
        with warnings.catch_warnings():
            # Chroma's cosine distance maps to relevance outside 0..1, so it warns
            # on every single search. The values still order and separate results
            # correctly (see MIN_RELEVANCE in retrieval/knowledge.py), so the
            # warning is noise rather than a signal.
            warnings.filterwarnings("ignore", message=".*Relevance scores must be between.*")
            # `sources` narrows the search to notes the topic index already
            # identified, so the ranking only has to pick the best SECTION of the
            # right note rather than find the right note at all.
            where = {"source": {"$in": sources}} if sources else None
            return get_vector_store(collection).similarity_search_with_relevance_scores(
                query, k=k, filter=where
            )
    except Exception as error:
        # Callers treat "no knowledge" as acceptable; log so a broken vector
        # store is visible instead of silently degrading to an ungrounded answer.
        print(f"[knowledge] scored search failed: {error}")
        return []


def search_knowledge_docs(query: str, k: int = 4, collection: str | None = None) -> list:
    """Top-k matching notes as raw LangChain Documents (unscored)."""
    try:
        return get_vector_store(collection).similarity_search(query, k=k)
    except Exception as error:
        print(f"[knowledge] search failed: {error}")
        return []




def alias_index_size(collection: str | None = None) -> int:
    """How many notes the alias index knows about. Published on /health.

    GraphRAG's coverage gate and its query expansion both read this index, so a
    zero here means the product refuses everything while every other signal
    still reads healthy. It is the one number that makes that visible.
    """
    try:
        return len(_get_index(collection).tokens)
    except Exception:  # noqa: BLE001 - health must never fail
        return 0
