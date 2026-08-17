"""
scripts/ingest_knowledge.py
----------------------------
Run this ONCE (and again whenever you add/edit knowledge files) to load the
Ayurveda/Yoga notes into the local vector database so the AI can search them.

What it does:
1. Reads every .md / .txt file in data/knowledge/.
2. Splits them into small chunks.
3. Stamps each chunk with the topic it belongs to (see `topic_header`).
4. Turns each chunk into searchable "embeddings".
5. Stores them in Chroma (data/vector_store/).

Run from the project root:
    python scripts/ingest_knowledge.py

The knowledge-file format is documented in `docs/knowledge-format.md`.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

# Make sure we can import our own "src" and "config" when run directly.
sys.path.append(str(Path(__file__).resolve().parents[1]))

import config
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from src.bots import get_bot
from src.knowledge import DEFAULT_COLLECTION_NAME, get_vector_store


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a `---` header off the top of a note, returning (fields, body).

    Deliberately not a YAML parser. The header only ever carries `topic` and
    `aliases`, and these notes are hand-written — a stray colon or an unquoted
    ampersand should not take down the whole ingest. Indented continuation lines
    are folded into the previous key so a long alias list can wrap.
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


def topic_header(topic: str, aliases: str) -> str:
    """The identity line stamped onto EVERY chunk of a note.

    Chunks are ~800 characters, so a note splits into four or five pieces and
    only the first carries the title. Without this the "Yoga & Breathing" section
    of acidity.md is an anonymous list of asanas: measured against the old
    corpus, `acidity gas` scored -0.018 and missed a file that is entirely about
    acidity, while `pcos ayurveda` scored 0.243 against digestion notes that
    never mention it.

    Repeating the topic and its aliases in every chunk is what lets a short
    query — especially a Hinglish one the note itself is not written in — match
    the right note, and it gives `retrieval/knowledge.py` a token to check the
    query against.
    """
    parts = []
    if topic:
        parts.append(f"Topic: {topic}")
    if aliases:
        parts.append(f"also called: {aliases}")
    return f"[{' | '.join(parts)}]\n" if parts else ""


def load_files() -> list[Document]:
    """Read all knowledge files into LangChain Document objects."""
    docs: list[Document] = []
    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    files = list(knowledge_dir.glob("*.md")) + list(knowledge_dir.glob("*.txt"))
    for file in files:
        raw = file.read_text(encoding="utf-8", errors="ignore")
        fields, body = parse_front_matter(raw)
        topic = fields.get("topic", "")
        aliases = fields.get("aliases", "")
        if not topic:
            # Not fatal — an unconverted note still ingests, it just retrieves
            # worse. Say so, because it is invisible otherwise.
            print(f"  ! {file.name} has no `topic:` front matter; retrieval will be weaker")
        docs.append(
            Document(
                page_content=body,
                metadata={
                    "source": file.name,
                    "topic": topic,
                    "aliases": aliases,
                    "header": topic_header(topic, aliases),
                },
            )
        )
    return docs


def chunk_id(chunk: Document, index: int) -> str:
    """A stable id derived from the chunk's own content.

    This is what makes re-ingesting idempotent. Previously `add_documents` was
    called with no ids, so Chroma minted a fresh uuid every run — and because
    `run_backend.bat` ingests on every launch, the corpus multiplied (42 stored
    embeddings for ~7 unique chunks). Retrieval then spent its whole top-k budget
    returning the same note four times.

    Keying on a content hash means re-running overwrites in place, and an edited
    note simply lands under a new id.
    """
    source = chunk.metadata.get("source", "notes")
    digest = hashlib.sha1(chunk.page_content.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{index}:{digest}"


def main() -> None:
    # WHICH BOT'S CORPUS THIS BUILDS.
    #
    # Was hardcoded to the one collection, which meant a second bot could be
    # CONFIGURED but never INGESTED — its collection would stay empty and it
    # would silently answer from nothing. `--collection` is what makes the Bot
    # Manager's isolation boundary usable rather than theoretical.
    #
    # Defaults to the default bot's collection, so every existing invocation —
    # `python scripts/ingest_knowledge.py`, the run_backend scripts, the docs —
    # keeps doing exactly what it did.
    parser = argparse.ArgumentParser(description="Build a bot's knowledge vector store.")
    parser.add_argument(
        "--collection",
        default=None,
        help=(
            "Chroma collection to write into. Defaults to the default bot's "
            "(see src/bots/registry.py). Must match that bot's "
            "BotConfig.knowledge_collection, or the bot will search an empty store."
        ),
    )
    parser.add_argument(
        "--bot",
        default=None,
        help="Resolve the collection from a registered bot_id instead of naming it.",
    )
    args = parser.parse_args()

    collection = args.collection
    if args.bot:
        if collection:
            raise SystemExit("Pass --bot or --collection, not both.")
        collection = get_bot(args.bot).knowledge_collection

    target = collection or DEFAULT_COLLECTION_NAME
    print(f"Ingesting into collection: {target}")

    docs = load_files()
    if not docs:
        print("No knowledge files found in", config.KNOWLEDGE_DIR)
        return

    # Split long notes into small, searchable chunks.
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_documents(docs)

    # Stamp the topic onto each piece BEFORE hashing, so editing the front matter
    # produces new ids and the old chunks get cleaned up as stale.
    for chunk in chunks:
        header = chunk.metadata.get("header", "")
        if header and not chunk.page_content.startswith(header):
            chunk.page_content = header + chunk.page_content

    ids = [chunk_id(chunk, i) for i, chunk in enumerate(chunks)]

    print(f"Loaded {len(docs)} files -> {len(chunks)} chunks. Building vector store...")
    store = get_vector_store(collection)

    # Drop anything left from the old id-less runs, and any chunk deleted from a
    # note since the last ingest. Without this the duplicates would persist.
    try:
        existing = store.get(include=[]).get("ids", [])
        stale = [i for i in existing if i not in set(ids)]
        if stale:
            store.delete(ids=stale)
            print(f"Removed {len(stale)} stale/duplicate chunk(s).")
    except Exception as error:  # noqa: BLE001 - a fresh store has nothing to clean
        print(f"(skipped cleanup: {error})")

    store.add_documents(chunks, ids=ids)
    print(f"Done! {len(chunks)} chunks ready for the AI to search.")


if __name__ == "__main__":
    main()
