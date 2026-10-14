"""The NCERT Knowledge Service as the tutor's knowledge source (app/rag/ncert.py), against a fake service."""

import json

import httpx
import pytest

from app.chat.assistant import retrieval_for
from app.learning.context import StudentContext, SubjectContext
from app.llm.base import ChatMessage
from app.rag.errors import RagError
from app.rag.graph import search_query_for
from app.rag.ncert import FAILURES_TO_PAUSE, NcertKnowledge, NcertRetriever
from app.rag.types import RetrievalOptions

RESULT = {
    "rank": 1,
    "chunk_id": "c1",
    "score": 0.81,
    "in_scope": True,
    "content": "Leaves have tiny pores called stomata.",
    "curriculum": {
        "classes": [7],
        "subject": {"id": "science", "name": "Science"},
        "book": {"id": "curiosity-c07-en", "title": "Curiosity"},
        "chapter": {"id": "ch1", "number": 1, "title": "Nutrition in Plants"},
    },
    "source": {"source_id": "s1", "printed_page_start": "12", "printed_page_end": "12"},
}


def knowledge(handler, calls=None):
    def record(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    return NcertKnowledge("http://127.0.0.1:4200", "ncertkb_test", 2.0, transport=httpx.MockTransport(record))


async def test_the_search_sends_the_question_and_the_curriculum_and_maps_cited_passages():
    calls = []
    payload = {
        "results": [RESULT, {"rank": 2, "content": "malformed: no provenance"}],
        "meta": {"kb_version": "c01-c08-v3"},
    }
    kb = knowledge(lambda request: httpx.Response(200, json=payload), calls)
    retriever = NcertRetriever(knowledge=kb, k=5, classes=(7,), subjects=("Science", "Social Science"))
    documents = await retriever.ainvoke("What are stomata?")

    request = calls[0]
    assert request.url.path == "/api/v1/retrieval/search"
    assert request.headers["authorization"] == "Bearer ncertkb_test"
    assert json.loads(request.content) == {
        "query": "What are stomata?",
        "mode": "vector",
        "top_k": 5,
        "filters": {"enforcement": "prefer", "any_of": [{"classes": [7], "subjects": ["science", "social-science"]}]},
    }
    assert len(documents) == 1  # the malformed result is dropped, the good one kept
    meta = documents[0].metadata
    assert meta["title"] == "NCERT Curiosity (Class 7), Ch 1: Nutrition in Plants, p. 12"
    assert (meta["source"], meta["chunk_id"], meta["kb_version"]) == ("NCERT", "c1", "c01-c08-v3")
    assert "search_ms" in retriever.last_timings
    await kb.aclose()


async def test_no_curriculum_means_no_filter():
    calls = []
    kb = knowledge(lambda request: httpx.Response(200, json={"results": [], "meta": {}}), calls)
    assert await NcertRetriever(knowledge=kb).ainvoke("photosynthesis") == []
    assert "filters" not in json.loads(calls[0].content)
    await kb.aclose()


async def test_failures_are_rag_errors_and_repeated_ones_pause_the_calls():
    def timeout(request):
        raise httpx.ConnectTimeout("slow")

    calls = []
    kb = knowledge(timeout, calls)
    for _ in range(FAILURES_TO_PAUSE):
        with pytest.raises(RagError) as error:
            await kb.search("q", 5, (), ())
        assert error.value.code == "ncert_timeout"
    with pytest.raises(RagError) as error:
        await kb.search("q", 5, (), ())
    assert error.value.code == "ncert_paused" and len(calls) == FAILURES_TO_PAUSE  # no call while paused
    await kb.aclose()

    for status, code in ((401, "ncert_unauthorized"), (503, "ncert_unavailable"), (200, "ncert_bad_response")):
        kb = knowledge(lambda request, status=status: httpx.Response(status, text="not json"))
        with pytest.raises(RagError) as error:
            await kb.search("q", 5, (), ())
        assert error.value.code == code
        await kb.aclose()


def test_a_short_follow_up_is_searched_with_the_question_before_it():
    def chat(*texts):
        return [ChatMessage("user" if i % 2 == 0 else "assistant", text) for i, text in enumerate(texts)]

    assert search_query_for(chat("What is photosynthesis?")) == "What is photosynthesis?"
    assert search_query_for(chat("What is photosynthesis?", "It is...", "Explain the second step")) == (
        "What is photosynthesis?\nExplain the second step"
    )
    long = "How do plants take in carbon dioxide from the air through their leaves?"
    assert search_query_for(chat("What is photosynthesis?", "It is...", long)) == long


def test_the_curriculum_comes_from_the_students_settings():
    assert retrieval_for(None) == RetrievalOptions()
    student = StudentContext(grade="Class 7", subjects=(SubjectContext("Science"), SubjectContext("Mathematics")))
    assert retrieval_for(student) == RetrievalOptions(classes=(7,), subjects=("Science", "Mathematics"))
    assert retrieval_for(StudentContext(grade="Undergraduate")) == RetrievalOptions()
