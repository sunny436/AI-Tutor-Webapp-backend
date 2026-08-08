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

import config
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

COLLECTION_NAME = "ayurveda_yoga"

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
_embeddings = None
_vector_store = None


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


def get_vector_store() -> Chroma:
    """Open the Ayurveda/Yoga vector DB once and reuse it."""
    global _vector_store
    if _vector_store is None:
        _vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embeddings(),
            persist_directory=config.VECTOR_DB_DIR,
            # Chroma defaults to L2. Cosine is what these sentence embeddings are
            # trained for, and it is what makes `relevance = 1 - distance` a
            # meaningful 0..1 number. Only read at collection creation time, so
            # changing it means wiping the store and re-ingesting.
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _vector_store


def warm_up() -> None:
    """Called at server startup so the first real answer is already fast."""
    try:
        get_vector_store().similarity_search("warm up", k=1)
        get_topic_index()
    except Exception:
        pass


# --- topic index ------------------------------------------------------------
# Built once from the `topic`/`aliases` front matter that ingest stored on every
# chunk. This is what makes retrieval work for Hinglish, which the embedding
# model handles unreliably: measured on this corpus, "pet phoolna" and "baal
# jhad rahe hain" did not return the right note anywhere in the top 12, even
# though both phrases are listed verbatim in that note's aliases. A keyword the
# author explicitly wrote down should never lose to a similarity score.
_topic_index: dict[str, set[str]] | None = None
_topic_phrases: dict[str, list[list[str]]] = {}
_token_df: dict[str, int] = {}

# Tier 2 only. A token appearing in more notes than this is filler that happened
# to land inside a longer alias phrase — "kaam" from "kisi kaam mein mann nahi
# lagta", "time" from "period time par nahi aata" — and proves nothing on its own.
MAX_DISTINCTIVE_DF = 2
# Enough weight to claim a topic in tier 2. One distinctive token reaches it; two
# ordinary ones do too; a single common word never does.
MIN_TOKEN_SCORE = 1.0


def get_topic_index() -> dict[str, set[str]]:
    """`{source filename: {searchable token, ...}}` from every note's front matter.

    Also fills `_topic_phrases`, which holds each `aliases:` entry as a whole
    phrase. Both views are needed and they answer different questions: the token
    set is a bag of words, the phrase list preserves the fact that the author
    wrote "triphala" as a complete search term but "kaam" only ever as one word
    inside a sentence.
    """
    global _topic_index
    if _topic_index is not None:
        return _topic_index

    index: dict[str, set[str]] = {}
    _topic_phrases.clear()
    try:
        stored = get_vector_store().get(include=["metadatas"])
        for meta in stored.get("metadatas") or []:
            source = (meta or {}).get("source")
            if not source or source in index:
                continue
            topic = (meta or {}).get("topic", "")
            aliases = (meta or {}).get("aliases", "")
            index[source] = {t for t in _tokens(f"{topic} {aliases}") if len(t) >= 2}
            # The topic title counts as a phrase too — it is how a note names
            # itself, and it is often what the user types.
            phrases = [_tokens(part) for part in f"{topic},{aliases}".split(",")]
            _topic_phrases[source] = [p for p in phrases if p]
    except Exception as error:
        print(f"[knowledge] could not build topic index: {error}")

    _token_df.clear()
    for tokens in index.values():
        for token in tokens:
            _token_df[token] = _token_df.get(token, 0) + 1

    _topic_index = index
    return index


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Does `needle` appear as a contiguous run inside `haystack`?"""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start] == first and haystack[start : start + len(needle)] == needle:
            return True
    return False


def match_topics(query: str, limit: int = 2) -> list[str]:
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

    get_topic_index()  # populates _topic_phrases and _token_df

    # --- tier 1: whole alias phrase present in the query ---------------------
    phrase_hits: list[tuple[int, str]] = []
    for source, phrases in _topic_phrases.items():
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
    index = get_topic_index()
    scored: list[tuple[float, str]] = []
    for source, alias_tokens in index.items():
        score = 0.0
        for token in query_tokens:
            frequency = _token_df.get(token, 0)
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


def search_knowledge_scored(query: str, k: int = 4, sources: list[str] | None = None) -> list[tuple]:
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
            return get_vector_store().similarity_search_with_relevance_scores(
                query, k=k, filter=where
            )
    except Exception as error:
        # Callers treat "no knowledge" as acceptable; log so a broken vector
        # store is visible instead of silently degrading to an ungrounded answer.
        print(f"[knowledge] scored search failed: {error}")
        return []


def search_knowledge_docs(query: str, k: int = 4) -> list:
    """Top-k matching notes as raw LangChain Documents (unscored)."""
    try:
        return get_vector_store().similarity_search(query, k=k)
    except Exception as error:
        print(f"[knowledge] search failed: {error}")
        return []


def search_knowledge(query: str, k: int = 4) -> str:
    """Find the top-k relevant Ayurveda/Yoga notes for a question."""
    try:
        results = get_vector_store().similarity_search(query, k=k)
        if not results:
            return ""
        chunks = []
        for i, doc in enumerate(results, start=1):
            source = doc.metadata.get("source", "knowledge")
            chunks.append(f"[Note {i} - from {source}]\n{doc.page_content}")
        return "\n\n".join(chunks)
    except Exception:
        return ""
