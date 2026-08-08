"""
scripts/eval_embeddings.py
--------------------------
Measure candidate embedding models against the real corpus and the real queries
users type, so the choice is evidence rather than reputation.

    python scripts/eval_embeddings.py
    python scripts/eval_embeddings.py --models BAAI/bge-m3,intfloat/multilingual-e5-base

WHAT IT MEASURES
For every query in `tests/retrieval_cases.py` it encodes the whole chunked
corpus, ranks chunks by cosine similarity, and reports:

  R@1 / R@4   how often the correct note is the top hit / in the top four.
              R@4 is the number that matters — the retriever keeps four chunks.
  margin      mean(best positive score) - mean(best negative score). This is the
              separation a relevance threshold has to live in. A model with
              great recall and no margin is unusable: nothing can tell an
              on-topic hit from an off-topic one, so off-topic questions get
              answered from whatever note scored least badly.

Scores are compared WITHIN a model, never across them — different models put
cosine similarity on different scales, which is exactly why the threshold has to
be re-tuned whenever the embedder changes.

Runs entirely locally. No API key, no cost; only the one-time model download.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from scripts.ingest_knowledge import load_files, topic_header  # noqa: E402
from tests.retrieval_cases import DEVANAGARI, ENGLISH, HINGLISH, NEGATIVES  # noqa: E402

CANDIDATES = [
    # current
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    # bigger sibling of the current model — same family, 768 dims
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    # E5 family: trained with an explicit query/passage asymmetry, which is what
    # short-question-against-long-note retrieval actually is.
    "intfloat/multilingual-e5-base",
    "intfloat/multilingual-e5-large",
    # BGE-M3: built for multilingual retrieval specifically.
    "BAAI/bge-m3",
]

# E5 was trained with these literal prefixes and loses a lot of accuracy without
# them. Everything else is used plain.
E5_QUERY = "query: "
E5_PASSAGE = "passage: "


def build_chunks() -> tuple[list[str], list[str]]:
    """The corpus exactly as `ingest_knowledge.py` would store it."""
    docs = load_files()
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    texts, sources = [], []
    for chunk in chunks:
        header = chunk.metadata.get("header", "")
        body = chunk.page_content
        texts.append(body if body.startswith(header) else header + body)
        sources.append(chunk.metadata.get("source", "?"))
    return texts, sources


def encode(model, texts: list[str], prefix: str) -> np.ndarray:
    vectors = model.encode(
        [prefix + t for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=32,
    )
    return np.asarray(vectors, dtype=np.float32)


def evaluate(name: str, texts: list[str], sources: list[str]) -> dict:
    from sentence_transformers import SentenceTransformer

    started = time.time()
    model = SentenceTransformer(name)
    is_e5 = "e5" in name.lower()

    passages = encode(model, texts, E5_PASSAGE if is_e5 else "")
    source_array = np.array(sources)

    report: dict = {"model": name, "dims": passages.shape[1]}
    positive_bests: list[float] = []

    for label, cases in (("hi", DEVANAGARI), ("hinglish", HINGLISH), ("en", ENGLISH)):
        queries = encode(model, [q for q, _ in cases], E5_QUERY if is_e5 else "")
        similarity = queries @ passages.T
        hit1 = hit4 = 0
        for row, (_, want) in zip(similarity, cases):
            order = np.argsort(-row)
            positive_bests.append(float(row[order[0]]))
            top = source_array[order]
            hit1 += want == top[0]
            # Distinct notes, not distinct chunks — one note can fill all four
            # slots, and that still counts as finding it.
            seen: list[str] = []
            for source in top:
                if source not in seen:
                    seen.append(source)
                if len(seen) == 4:
                    break
            hit4 += want in seen
        report[f"{label}@1"] = round(hit1 / len(cases), 3)
        report[f"{label}@4"] = round(hit4 / len(cases), 3)

    negatives = encode(model, NEGATIVES, E5_QUERY if is_e5 else "")
    negative_bests = (negatives @ passages.T).max(axis=1)

    report["pos_mean"] = round(float(np.mean(positive_bests)), 3)
    report["neg_max"] = round(float(np.max(negative_bests)), 3)
    report["margin"] = round(float(np.mean(positive_bests) - np.mean(negative_bests)), 3)
    # The realistic threshold: above every off-topic query, below as many
    # on-topic ones as possible.
    report["clean_gap"] = round(float(np.min(positive_bests) - np.max(negative_bests)), 3)
    report["seconds"] = round(time.time() - started, 1)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="", help="comma-separated overrides")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()] or CANDIDATES
    texts, sources = build_chunks()
    print(f"corpus: {len(texts)} chunks over {len(set(sources))} notes")
    print(f"queries: {len(DEVANAGARI)} devanagari, {len(HINGLISH)} hinglish, "
          f"{len(ENGLISH)} english, {len(NEGATIVES)} negatives")
    print(f"current: {config.EMBEDDING_MODEL}\n")

    results = []
    for name in models:
        try:
            report = evaluate(name, texts, sources)
        except Exception as error:  # noqa: BLE001 - one bad model must not end the run
            print(f"SKIP {name}: {str(error)[:120]}")
            continue
        results.append(report)
        print(
            f"RESULT {name:62} dims={report['dims']:5} "
            f"hi@1={report['hi@1']:.2f} hi@4={report['hi@4']:.2f} | "
            f"hin@1={report['hinglish@1']:.2f} hin@4={report['hinglish@4']:.2f} | "
            f"en@1={report['en@1']:.2f} en@4={report['en@4']:.2f} | "
            f"margin={report['margin']:.3f} gap={report['clean_gap']:+.3f} "
            f"({report['seconds']}s)"
        )

    if not results:
        return
    print("\n--- ranked by hinglish@4, then margin (hinglish is the hard case) ---")
    for report in sorted(results, key=lambda r: (-r["hinglish@4"], -r["margin"])):
        print(f"  {report['hinglish@4']:.3f}  margin {report['margin']:+.3f}  {report['model']}")


if __name__ == "__main__":
    main()
