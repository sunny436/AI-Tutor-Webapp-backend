"""
knowledge.py
------------
Ayurveda/Yoga knowledge search (the "RAG" part), with CACHING for speed.

IMPORTANT (performance): the embedding model and the vector database are loaded
ONCE and reused for every request. Earlier they were re-loaded on every message,
which made each answer very slow. Now the first request warms them up and the
rest are fast.
"""

import re
import warnings
from dataclasses import dataclass, field

import config
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

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
# The embedding MODEL is shared across collections on purpose — it is ~1.9GB and
# carries no per-collection state. The vector STORES are keyed by collection,
# which is what keeps uploaded reports out of the shared notes.
_embeddings = None
_vector_stores: dict[str, Chroma] = {}


def get_embeddings():
    """Load the (free, local) embedding model once and reuse it.

    `normalize_embeddings` matters for scoring, not for ranking. Without it the
    vectors keep their raw magnitude, Chroma's L2 distances come out large, and
    the relevance mapping returns values like -17 for a chunk that is in fact the
    correct one. Unit-length vectors put cosine distance in 0..2, so relevance
    lands in a 0..1 range that a threshold can actually be set against.
    """
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
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
            persist_directory=config.VECTOR_DB_DIR,
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


def _get_index(collection: str | None = None) -> _TopicIndex:
    """Build (once) and return one collection's alias index."""
    name = _resolve(collection)
    cached = _topic_indexes.get(name)
    if cached is not None:
        return cached

    built = _TopicIndex()
    try:
        stored = get_vector_store(name).get(include=["metadatas"])
        for meta in stored.get("metadatas") or []:
            source = (meta or {}).get("source")
            if not source or source in built.tokens:
                continue
            topic = (meta or {}).get("topic", "")
            aliases = (meta or {}).get("aliases", "")
            built.tokens[source] = {
                t for t in _tokens(f"{topic} {aliases}") if len(t) >= 2
            }
            # The topic title counts as a phrase too — it is how a note names
            # itself, and it is often what the user types.
            phrases = [_tokens(part) for part in f"{topic},{aliases}".split(",")]
            built.phrases[source] = [p for p in phrases if p]
    except Exception as error:
        print(f"[knowledge] could not build topic index for {name!r}: {error}")

    for tokens in built.tokens.values():
        for token in tokens:
            built.token_df[token] = built.token_df.get(token, 0) + 1

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


def search_knowledge(query: str, k: int = 4, collection: str | None = None) -> str:
    """Find the top-k relevant Ayurveda/Yoga notes for a question."""
    try:
        results = get_vector_store(collection).similarity_search(query, k=k)
        if not results:
            return ""
        chunks = []
        for i, doc in enumerate(results, start=1):
            source = doc.metadata.get("source", "knowledge")
            chunks.append(f"[Note {i} - from {source}]\n{doc.page_content}")
        return "\n\n".join(chunks)
    except Exception:
        return ""
