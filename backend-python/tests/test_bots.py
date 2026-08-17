"""
The Bot Manager, and the knowledge isolation guarantee around it.

    python tests/test_bots.py

No LLM is involved, on purpose — same reasoning as tests/test_memory.py. Bot
isolation is a data-access boundary, and a boundary that only holds when a model
happens to cooperate is not a boundary.

THE ASSERTION THAT MATTERS
Bot A must never retrieve Bot B's curated knowledge. Everything else here checks
that the feature works; this one checks that it is safe to add a second bot.

It is enforced in two independent places, and both are checked below:

  1. `get_bot` refuses an unregistered bot_id outright, so an unknown id never
     reaches a retriever — the HTTP edge turns that refusal into a 400;
  2. the knowledge retriever reads its Chroma collection from the request's
     BotConfig, so a bot configured with a different collection physically
     searches different data.

BOTH HALVES OF (2) ARE TESTED. Scoping the vector store but not the alias index
would still leak: `match_topics` would hand back the OTHER bot's note filenames,
and the retriever searches claimed sources by name while skipping the relevance
threshold. So the index is asserted separately from the search.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src import knowledge  # noqa: E402
from src.bots import BOTS, BotConfig, UnknownBotError, get_bot  # noqa: E402
from src.retrieval.base import RetrievalContext  # noqa: E402
from src.retrieval.knowledge import KnowledgeRetriever  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# The throwaway bot's collection. Named so that if one ever turns up in a real
# vector store it is obvious where it came from.
#
# THE NAME MUST BE VALID FOR CHROMA (3-512 chars, [a-zA-Z0-9._-], starting and
# ending alphanumeric). The first version of this test used leading underscores;
# Chroma rejected the name outright, both lookups errored, and the isolation
# assertion passed because nothing could be searched AT ALL. A test that passes
# because the query crashed is worse than no test — it reports a boundary as
# proven when it was never exercised.
PROBE_COLLECTION = "p1-bot-isolation-probe"
PROBE_BOT = BotConfig(
    bot_id="probe",
    knowledge_collection=PROBE_COLLECTION,
    display_name="throwaway test bot",
)

# The probe bot's entire corpus: one note that could not be less Ayurvedic. It
# gives the test a second direction to check — Ayurveda must not see this either.
PROBE_SOURCE = "rocket-engines.md"
PROBE_TEXT = (
    "Rocket engines generate thrust by expelling combustion products through a "
    "de Laval nozzle. Specific impulse measures propellant efficiency."
)
PROBE_QUERY = "rocket nozzle thrust"

# Hinglish, and known to match the corpus: "gas ki problem" scores ~0.59 against
# gas-bloating.md (see the measurements in src/retrieval/knowledge.py).
QUERY = "gas ki problem"


def retrieve(bot: BotConfig) -> list:
    """Run the real knowledge retriever as one bot, return its chunks."""
    result = asyncio.run(
        KnowledgeRetriever(enabled=True).retrieve(RetrievalContext(query=QUERY, bot=bot))
    )
    return list(result.chunks)


# --- 1. the registry ---------------------------------------------------------
print("\nregistry")

check("absent bot_id resolves to the default bot", get_bot(None).bot_id == "ayurveda")
check("empty bot_id resolves to the default bot", get_bot("").bot_id == "ayurveda")
check("explicit 'ayurveda' resolves", get_bot("ayurveda").bot_id == "ayurveda")
check(
    "the ayurveda bot still owns today's collection",
    get_bot("ayurveda").knowledge_collection == "ayurveda_yoga",
    get_bot("ayurveda").knowledge_collection,
)
check("only one bot is registered", list(BOTS) == ["ayurveda"], str(list(BOTS)))

try:
    resolved = get_bot("yoga")
    # The dangerous failure is not an exception — it is a SILENT fallback, which
    # would answer out of Ayurveda's corpus for a caller that asked for Yoga.
    check("unknown bot_id is rejected", False, f"silently fell back to {resolved.bot_id!r}")
except UnknownBotError:
    check("unknown bot_id raises rather than falling back", True)

check(
    "RetrievalContext defaults to the default bot (existing callers unchanged)",
    RetrievalContext(query="x").bot.knowledge_collection == "ayurveda_yoga",
)


# --- 2. isolation ------------------------------------------------------------
print("\nisolation")

# Baseline FIRST, against the real vector store. Without this the probe below
# would "pass" simply because retrieval is broken or the DB was never ingested —
# a vacuous test that proves nothing.
baseline = retrieve(get_bot("ayurveda"))
check(
    f"baseline: the ayurveda bot retrieves content for {QUERY!r}",
    len(baseline) > 0,
    f"{len(baseline)} chunks",
)
check(
    "baseline chunks really are ayurveda notes",
    all(c.source.startswith("knowledge:") for c in baseline) and len(baseline) > 0,
    ", ".join(sorted({c.source for c in baseline})) or "none",
)

# The probe collection is created in a THROWAWAY directory, so this test never
# writes an empty collection into the real vector store.
probe_dir = tempfile.mkdtemp(prefix="p1-bot-isolation-")
real_dir = config.VECTOR_DB_DIR
try:
    config.VECTOR_DB_DIR = probe_dir

    # Give the probe bot a real, non-empty corpus of its own. An EMPTY collection
    # would make "retrieved nothing" ambiguous — it could mean isolation worked,
    # or that the store was simply broken. A populated one distinguishes them:
    # the probe must retrieve ITS note and never Ayurveda's.
    probe_store = knowledge.get_vector_store(PROBE_COLLECTION)
    probe_store.add_texts(
        [PROBE_TEXT],
        metadatas=[
            {"source": PROBE_SOURCE, "topic": "Rocket Engines", "aliases": "rocket, nozzle, thrust"}
        ],
    )
    knowledge._topic_indexes.pop(PROBE_COLLECTION, None)  # rebuild with the new note

    check(
        "sanity: the probe collection is real and searchable",
        len(knowledge.search_knowledge_scored(PROBE_QUERY, 4, collection=PROBE_COLLECTION)) > 0,
        "if this fails, the assertions below prove nothing",
    )

    # --- direction 1: probe must not see Ayurveda ---------------------------
    probe_chunks = retrieve(PROBE_BOT)
    leaked = [c.source for c in probe_chunks if PROBE_SOURCE not in c.source]
    check(
        "THE ISOLATION TEST: the probe bot cannot retrieve Ayurveda content",
        not leaked,
        f"leaked {len(leaked)}: " + ", ".join(leaked[:4]),
    )

    # If the alias index were shared, this would claim gas-bloating.md even
    # though the probe's store has never seen it — and the retriever fetches
    # claimed sources BY NAME, skipping the relevance floor entirely.
    probe_topics = knowledge.match_topics(QUERY, collection=PROBE_COLLECTION)
    ayurveda_topics = knowledge.match_topics(QUERY, collection="ayurveda_yoga")
    check(
        "the alias index is scoped too: probe claims no ayurveda note",
        probe_topics == [],
        str(probe_topics),
    )
    check(
        "...while the ayurveda index still claims its own",
        len(ayurveda_topics) > 0,
        str(ayurveda_topics),
    )

    # --- direction 2: Ayurveda must not see the probe -----------------------
    check(
        "the probe bot CAN reach its own note (so the test is not vacuous)",
        knowledge.match_topics(PROBE_QUERY, collection=PROBE_COLLECTION) == [PROBE_SOURCE],
        str(knowledge.match_topics(PROBE_QUERY, collection=PROBE_COLLECTION)),
    )
    check(
        "the ayurveda bot cannot see the probe's note",
        PROBE_SOURCE not in knowledge.match_topics(PROBE_QUERY, collection="ayurveda_yoga"),
        str(knowledge.match_topics(PROBE_QUERY, collection="ayurveda_yoga")),
    )
    ayurveda_on_probe_query = [
        c.source for c in retrieve(get_bot("ayurveda")) if PROBE_SOURCE in c.source
    ]
    check(
        "no probe content reaches an ayurveda retrieval",
        not ayurveda_on_probe_query,
        str(ayurveda_on_probe_query),
    )
finally:
    config.VECTOR_DB_DIR = real_dir
    knowledge._vector_stores.pop(PROBE_COLLECTION, None)
    knowledge._topic_indexes.pop(PROBE_COLLECTION, None)
    shutil.rmtree(probe_dir, ignore_errors=True)

# The real store must be untouched by all of the above.
after = retrieve(get_bot("ayurveda"))
check(
    "the ayurveda bot is unaffected by the probe",
    len(after) == len(baseline),
    f"{len(baseline)} -> {len(after)}",
)


# --- 3. the HTTP edge --------------------------------------------------------
print("\nHTTP edge")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

# A tripwire in place of the retrieval pipeline. If bot validation happens where
# it should, an unknown bot_id never gets far enough to call this.
pipeline_calls: list[str] = []
real_get_pipeline = server.run_consult_turn.__globals__["get_pipeline"]


def tripwire():
    pipeline_calls.append("called")
    return real_get_pipeline()


server.run_consult_turn.__globals__["get_pipeline"] = tripwire

# `require_user` accepts a service key as an alternative credential, which is how
# the suite exercises /consult without minting a login.
real_service_key = config.SERVICE_KEY
try:
    config.SERVICE_KEY = "p1-test-service-key"
    client = TestClient(server.app)
    headers = {"X-Service-Key": config.SERVICE_KEY}

    response = client.post(
        "/consult", json={"problem": "hi", "bot_id": "definitely-not-a-bot"}, headers=headers
    )
    check("unknown bot_id returns HTTP 400", response.status_code == 400, str(response.status_code))
    check(
        "the 400 names the offending bot_id",
        "definitely-not-a-bot" in response.text,
        response.text[:120],
    )
    check(
        "unknown bot_id never reaches retrieval",
        not pipeline_calls,
        f"pipeline invoked {len(pipeline_calls)}x",
    )

    stream = client.post(
        "/consult/stream",
        json={"problem": "hi", "bot_id": "definitely-not-a-bot"},
        headers=headers,
    )
    check(
        "/consult/stream also rejects with 400, not a mid-stream error frame",
        stream.status_code == 400,
        str(stream.status_code),
    )
    check("streaming path also never reaches retrieval", not pipeline_calls)
finally:
    config.SERVICE_KEY = real_service_key
    server.run_consult_turn.__globals__["get_pipeline"] = real_get_pipeline

# Absence is checked at the function the endpoint calls, rather than by running a
# whole turn — that would spend an LLM call to assert something about routing.
check(
    "absent bot_id resolves to ayurveda (today's behaviour)",
    server._resolve_bot({}).bot_id == "ayurveda",
)
check(
    "explicit bot_id='ayurveda' resolves to the same config",
    server._resolve_bot({"bot_id": "ayurveda"}) is server._resolve_bot({}),
)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== bots: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
