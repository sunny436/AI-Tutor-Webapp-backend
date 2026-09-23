"""Guards: no external graph-RAG product or other vector database, and the dependency direction holds.

FastAPI routes -> ChatService -> LangGraph (app.rag.graph) -> LangChain retriever -> KnowledgeStore -> PostgreSQL
"""

import ast
import importlib.util
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import EMBEDDING_DIMENSIONS
from app.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
# Built from parts so this file does not match its own scan.
FORBIDDEN = re.compile(
    "|".join(["graph" + "rag", "graph_" + "rag", "graph-" + "rag", "chroma", "pinecone", "weaviate", "qdrant"]),
    re.IGNORECASE,
)
SCANNED = [
    *BACKEND.joinpath("app").rglob("*.py"),
    *BACKEND.joinpath("alembic").rglob("*.py"),
    *BACKEND.joinpath("scripts").rglob("*.py"),
    *[p for p in BACKEND.joinpath("tests").rglob("*.py") if p.name != Path(__file__).name],
    BACKEND / "requirements.txt",
    BACKEND / "requirements-dev.txt",
    BACKEND / ".env.example",
    *REPO.joinpath("deploy").rglob("*"),
    *REPO.joinpath(".github").rglob("*"),
    REPO / "docker-compose.dev.yml",
    REPO / ".gitignore",
]


def test_no_external_graph_rag_or_other_vector_database_referenced():
    hits = []
    for path in SCANNED:
        if path.is_file():
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()[:100]}")
    assert hits == []


def test_forbidden_packages_are_not_installed():
    for module in ("chromadb", "pinecone", "weaviate", "qdrant_client", "graph" + "rag", "langchain_postgres"):
        assert importlib.util.find_spec(module) is None, module


def test_rag_stack_is_langchain_and_langgraph():
    for module in ("langchain_core", "langgraph", "langchain_text_splitters", "pgvector"):
        assert importlib.util.find_spec(module) is not None, module


def test_no_route_or_setting_for_an_external_rag_service(app):
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [p for p in paths if FORBIDDEN.search(p) or "rag" in p.lower()]
    assert not [name for name in Settings.model_fields if FORBIDDEN.search(name)]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_dependency_direction():
    app_dir = BACKEND / "app"
    for router in app_dir.rglob("router.py"):  # HTTP layer never reaches retrieval or vectors
        bad = {m for m in _imports(router) if m.startswith(("app.rag", "pgvector"))}
        assert not bad, (router.name, bad)
    for module in app_dir.joinpath("chat").glob("*.py"):  # chat talks to the graph only
        bad = {m for m in _imports(module) if m.startswith("app.rag") and m != "app.rag.graph"}
        bad |= {m for m in _imports(module) if m.startswith(("pgvector", "langchain", "langgraph"))}
        assert not bad, (module.name, bad)
    graph_imports = _imports(app_dir / "rag" / "graph.py")  # graph depends on abstractions only
    assert not {
        m
        for m in graph_imports
        if m
        in {
            "app.llm.openai_compatible",
            "app.llm.fallback",
            "app.llm.fake",
            "app.llm.factory",
            "app.rag.store",
            "app.rag.embeddings",
            "app.rag.retriever",
        }
        or m.startswith(("sqlalchemy", "pgvector", "openai"))
    }
    for module in [*app_dir.joinpath("db").glob("*.py"), app_dir / "rag" / "store.py"]:
        assert not {m for m in _imports(module) if m.startswith(("langchain", "langgraph"))}, module.name


async def test_embedding_dimension_matches_everywhere(database):
    assert Settings(_env_file=None).embedding_dimensions == EMBEDDING_DIMENSIONS == 1536
    engine = create_async_engine(database)
    async with engine.connect() as conn:
        column = await conn.scalar(
            text(
                "select format_type(atttypid, atttypmod) from pg_attribute "
                "where attrelid = 'document_chunks'::regclass and attname = 'embedding'"
            )
        )
    await engine.dispose()
    assert column == f"vector({EMBEDDING_DIMENSIONS})"
