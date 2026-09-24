"""Measure retrieval quality on your own labelled questions (to calibrate RAG_MIN_SCORE).

    python scripts/eval_retrieval.py --cases cases.jsonl [--as-user EMAIL] [--k 5]

cases.jsonl, one JSON object per line: {"query": "...", "expected_uri": "path/in/source.md"}
(optionally "source": "name" to restrict the search). Prints hit@1, hit@k, MRR and the
score distribution of correct vs. incorrect top results. Meaningful only with the real
embedding provider (EMBEDDING_PROVIDER=openai_compatible and a valid key).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args: argparse.Namespace, cases: list[dict]) -> int:
    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import Database
    from app.rag.embeddings import build_embeddings
    from app.rag.retriever import PgVectorRetriever
    from app.rag.store import KnowledgeStore
    from app.rag.types import AccessScope
    from app.settings import get_settings

    settings = get_settings()
    db = Database(settings)
    try:
        user_id = None
        if args.as_user:
            async with db.sessionmaker() as session:
                user_id = await session.scalar(select(User.id).where(User.email == args.as_user))
        store = KnowledgeStore(db, settings.rag_hnsw_ef_search)
        embeddings = build_embeddings(settings)
        hit1 = hitk = 0
        reciprocal = []
        correct_scores, wrong_scores = [], []
        for case in cases:
            retriever = PgVectorRetriever(
                store=store,
                embeddings=embeddings,
                scope=AccessScope(user_id),
                k=args.k,
                min_score=0.0,  # measure the raw distribution
                source_names=[case["source"]] if case.get("source") else None,
            )
            docs = await retriever.ainvoke(case["query"])
            uris = [d.metadata["uri"] for d in docs]
            rank = uris.index(case["expected_uri"]) + 1 if case["expected_uri"] in uris else None
            hit1 += rank == 1
            hitk += rank is not None
            reciprocal.append(1 / rank if rank else 0.0)
            if docs:
                (correct_scores if rank == 1 else wrong_scores).append(docs[0].metadata["score"])
        n = max(len(cases), 1)
        print(f"cases={len(cases)} hit@1={hit1 / n:.2f} hit@{args.k}={hitk / n:.2f} mrr={sum(reciprocal) / n:.2f}")
        for name, scores in (("correct top-1", correct_scores), ("incorrect top-1", wrong_scores)):
            if scores:
                print(
                    f"{name}: n={len(scores)} min={min(scores):.3f} median={statistics.median(scores):.3f} "
                    f"max={max(scores):.3f}"
                )
        print("Choose RAG_MIN_SCORE between the incorrect and correct distributions.")
        return 0
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--as-user", help="evaluate with this user's access scope (default: global sources only)")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    lines = Path(args.cases).read_text(encoding="utf-8").splitlines()
    return asyncio.run(run(args, [json.loads(line) for line in lines if line.strip()]))


if __name__ == "__main__":
    raise SystemExit(main())
