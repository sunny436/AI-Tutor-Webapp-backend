"""
user_documents.py
-----------------
Private, per-user document index — uploaded lab reports, prescriptions, scans.

This is deliberately a SEPARATE Chroma collection from the Ayurveda/Yoga notes.
The knowledge corpus is curated, shared and safe to show anybody; a blood report
is none of those things. Keeping them in one collection would mean every ordinary
question was one missing filter away from returning somebody's medical history.

Isolation is by `user_id` metadata on every chunk plus a `where` filter on every
query — the same mechanism `knowledge.search_knowledge_scored` already uses to
filter by source, so it is a proven path rather than a new one.

One collection with a filter, rather than a collection per user, on purpose:
collections-per-user grows without bound, needs its own lifecycle code, and puts
an unbounded number of HNSW indexes on disk for what a metadata field does just
as well.
"""

from __future__ import annotations

import hashlib

import config
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.knowledge import get_embeddings

COLLECTION_NAME = "user_documents"

# Reports are dense and full of numbers. Smaller chunks than the knowledge notes
# use, so a single lab value does not get averaged away inside a long block.
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100

# A document that produced fewer characters than this was almost certainly a
# failed read - an image with no OCR available, or an encrypted PDF - and
# indexing it would add noise while telling the user it worked.
MIN_USEFUL_CHARS = 40

_store: Chroma | None = None


def get_store() -> Chroma:
    """Open the private document collection once and reuse it."""
    global _store
    if _store is None:
        _store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embeddings(),
            persist_directory=config.VECTOR_DB_DIR,
            # Must match the knowledge store: the same embeddings are used, and
            # relevance is read as `1 - distance`, which only holds for cosine.
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _store


def _chunk_id(user_id: str, filename: str, index: int) -> str:
    """A stable id, so re-uploading the same file REPLACES rather than duplicates.

    Without this, uploading a report twice would put two copies of every chunk in
    the index and the model would see the same lab value repeated - which reads
    as corroboration when it is just a double upload.
    """
    seed = f"{user_id}:{filename}:{index}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()


def index_document(user_id: str, filename: str, text: str) -> int:
    """Embed one document's text against a user. Returns the number of chunks.

    Returns 0 without touching the store when there is no user, so an anonymous
    upload can never write into the index. That check is here, at the write
    point, as well as at the read point - either alone would be enough, but this
    is the one place where being paranoid costs nothing.
    """
    if not user_id or not (text or "").strip():
        return 0
    if len(text.strip()) < MIN_USEFUL_CHARS:
        return 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    if not chunks:
        return 0

    documents = [
        Document(
            page_content=chunk,
            metadata={"user_id": user_id, "filename": filename, "chunk": i},
        )
        for i, chunk in enumerate(chunks)
    ]
    ids = [_chunk_id(user_id, filename, i) for i in range(len(chunks))]

    store = get_store()
    # Delete first: a shorter re-upload would otherwise leave the tail chunks of
    # the previous version behind, since only the ids it reuses get overwritten.
    remove_document(user_id, filename)
    store.add_documents(documents, ids=ids)
    return len(chunks)


def search(user_id: str, query: str, k: int = 4) -> list[tuple[str, str, float]]:
    """Search one user's documents. Returns (filename, text, relevance) triples.

    Returns nothing at all when `user_id` is empty. This is the single most
    important line in the file: an unfiltered query here would hand one person's
    medical reports to whoever asked next. It fails closed by construction rather
    than by a reviewer noticing.
    """
    if not user_id or not (query or "").strip():
        return []

    try:
        hits = get_store().similarity_search_with_relevance_scores(
            query,
            k=k,
            filter={"user_id": user_id},
        )
    except Exception as error:  # noqa: BLE001
        print(f"[user_documents] search failed: {error}")
        return []

    return [
        (doc.metadata.get("filename", "document"), doc.page_content, score)
        for doc, score in hits
    ]


def remove_document(user_id: str, filename: str) -> None:
    """Drop every chunk of one document. Called on re-upload and on delete.

    Deleting the file in Convex without calling this would leave the report
    answering questions after the user believed they had removed it.
    """
    if not user_id or not filename:
        return
    try:
        get_store().delete(where={"$and": [
            {"user_id": user_id},
            {"filename": filename},
        ]})
    except Exception as error:  # noqa: BLE001
        print(f"[user_documents] delete failed: {error}")


def list_documents(user_id: str) -> list[str]:
    """Filenames this user has indexed, for showing in the UI."""
    if not user_id:
        return []
    try:
        got = get_store().get(where={"user_id": user_id}, include=["metadatas"])
    except Exception as error:  # noqa: BLE001
        print(f"[user_documents] list failed: {error}")
        return []
    seen = {m.get("filename") for m in (got.get("metadatas") or []) if m}
    return sorted(name for name in seen if name)
