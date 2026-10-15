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


def test_the_learning_domain_is_reached_only_through_its_public_modules():
    """Other domains read a student's context (app.learning.context) and render the tutor's
    instructions (app.learning.tutor); only the composition root mounts its router. Nothing
    else reaches into Learning's tables or service, and Learning depends on no other domain, but
    for one read: its router's tutor preview takes the "Learning so far" line from Progress's
    public module, exactly as the chat does."""
    app_dir = BACKEND / "app"
    public = {"app.learning.context", "app.learning.tutor"}
    for module in app_dir.rglob("*.py"):
        if app_dir / "learning" in module.parents:
            continue
        allowed = public | ({"app.learning.router"} if module.name == "main.py" else set())
        reached = {m for m in _imports(module) if m.startswith("app.learning")}
        assert reached <= allowed, (module.relative_to(app_dir), reached - allowed)
    for module in app_dir.joinpath("learning").glob("*.py"):
        other_domains = {
            m for m in _imports(module) if m.startswith(("app.chat", "app.conversations", "app.rag", "app.llm"))
        }
        assert not other_domains, (module.name, other_domains)
        progress = {m for m in _imports(module) if m.startswith("app.progress")}
        assert progress <= ({"app.progress.learning"} if module.name == "router.py" else set()), (module.name, progress)


def test_the_progress_domain_is_reached_only_through_its_public_module():
    """Chat records questions (app.progress.activity) and learning (app.progress.learning, which
    notifications also read for the streak); only the composition root mounts the router. Progress
    reads the goals through Learning's public module and nothing else of another domain."""
    app_dir = BACKEND / "app"
    for module in app_dir.rglob("*.py"):
        if app_dir / "progress" in module.parents:
            continue
        allowed = {"app.progress.activity", "app.progress.learning"}
        allowed |= {"app.progress.router"} if module.name == "main.py" else set()
        reached = {m for m in _imports(module) if m.startswith("app.progress")}
        assert reached <= allowed, (module.relative_to(app_dir), reached - allowed)
    for module in app_dir.joinpath("progress").glob("*.py"):
        reached = {m for m in _imports(module) if m.startswith(("app.chat", "app.conversations", "app.rag", "app.llm"))}
        reached |= {m for m in _imports(module) if m.startswith("app.learning") and m != "app.learning.context"}
        assert not reached, (module.name, reached)


def test_the_question_bank_never_calls_a_model():
    """Questions are picked, served and checked by SQL and fixed rules only (docs/question_bank.md):
    the bank's code and its scripts import no model, retrieval, chat or HTTP client."""
    files = [
        *BACKEND.joinpath("app", "qbank").glob("*.py"),
        BACKEND / "scripts" / "import_questions.py",
        BACKEND / "scripts" / "qbank_coverage.py",
    ]
    assert len(files) >= 6
    forbidden = ("app.llm", "app.rag", "app.chat", "app.assessments", "langchain", "langgraph", "openai", "httpx")
    for path in files:
        bad = {m for m in _imports(path) if m.startswith(forbidden)}
        assert not bad, (path.name, bad)


async def test_embedding_dimension_matches_everywhere(database):
    assert Settings(_env_file=None).embedding_dimensions == EMBEDDING_DIMENSIONS == 1536
    engine = create_async_engine(database)
    async with engine.connect() as conn:
        columns = {
            table: await conn.scalar(
                text(
                    "select format_type(atttypid, atttypmod) from pg_attribute "
                    f"where attrelid = '{table}'::regclass and attname = 'embedding'"
                )
            )
            for table in ("document_chunks", "file_chunks")
        }
    await engine.dispose()
    assert columns == {table: f"vector({EMBEDDING_DIMENSIONS})" for table in columns}


def test_notifications_and_support_are_reached_only_through_their_public_modules():
    """Other domains queue email (outbox), security alerts (alerts), add in-app notifications
    (inbox) or use the email texts (emails); the worker plans and sends; the composition root
    mounts the routers. The jobs worker is only ever started as its own process, never imported
    by the API."""
    app_dir = BACKEND / "app"
    public = {
        "app.notifications.outbox",
        "app.notifications.alerts",
        "app.notifications.emails",
        "app.notifications.inbox",
    }
    for module in app_dir.rglob("*.py"):
        if app_dir / "notifications" in module.parents:
            continue
        allowed = set(public)
        if module.name == "main.py":
            allowed |= {"app.notifications.router", "app.support.router"}
        if app_dir / "jobs" in module.parents:
            allowed |= {"app.notifications.reminders", "app.notifications.sender"}
        reached = {m for m in _imports(module) if m.startswith("app.notifications")}
        assert reached <= allowed, (module.relative_to(app_dir), reached - allowed)
        if app_dir / "support" not in module.parents:
            assert not {m for m in _imports(module) if m.startswith("app.support")} - allowed, module.name
        if app_dir / "jobs" not in module.parents:
            assert not {m for m in _imports(module) if m.startswith("app.jobs")}, module.name
