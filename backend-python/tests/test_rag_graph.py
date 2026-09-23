"""The LangGraph workflow in isolation: node order, streaming, skip paths, failures, cancellation."""

import asyncio

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.llm.base import ChatMessage, GenerationOptions, LLMUnavailable
from app.llm.fake import FakeProvider
from app.rag.errors import EmbeddingError, RetrievalError
from app.rag.graph import NODES, RagDependencies, RetrievalOptions, build_rag_graph
from tests.conftest import make_settings

DOC = Document(
    page_content="The Zephyr protocol listens on port 7777.",
    metadata={
        "chunk_id": "c1",
        "document_id": "d1",
        "source_id": "s1",
        "source": "kb",
        "title": "Zephyr",
        "uri": "zephyr.md",
        "ordinal": 0,
        "score": 0.8,
    },
)


class StaticRetriever(BaseRetriever):
    documents: list = []
    error: object = None
    delay: float = 0.0

    def _get_relevant_documents(self, query, *, run_manager):  # pragma: no cover
        raise NotImplementedError

    async def _aget_relevant_documents(self, query, *, run_manager):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return list(self.documents)


class Harness:
    def __init__(
        self, *, documents=(DOC,), error=None, delay=0.0, has_knowledge=True, configured=True, llm=None, **settings
    ):
        self.llm = llm or FakeProvider()
        self.factory_calls = 0
        self.knowledge_checks = 0
        self.retriever = StaticRetriever(documents=list(documents), error=error, delay=delay)

        def factory(scope, options):
            self.factory_calls += 1
            return self.retriever

        async def knowledge(scope):
            self.knowledge_checks += 1
            return has_knowledge

        self.graph = build_rag_graph(
            RagDependencies(
                llm=self.llm,
                retriever_factory=factory,
                has_knowledge=knowledge,
                embeddings_configured=configured,
                settings=make_settings(**settings),
            )
        )

    @staticmethod
    def state(question="Which port does Zephyr use?", retrieval=RetrievalOptions()):
        return {
            "user_id": None,
            "conversation": [ChatMessage("user", question)],
            "system_prompt": "You are helpful.",
            "retrieval": retrieval,
            "generation": GenerationOptions(),
        }

    async def run(self, **state_kwargs):
        events = [e async for e in self.graph.astream(self.state(**state_kwargs), stream_mode="custom")]
        summary = next(e["summary"] for e in events if e["event"] == "retrieval")
        text = "".join(e["text"] for e in events if e["event"] == "token")
        return events, summary, text


def test_graph_has_the_four_nodes_in_order():
    graph = Harness().graph.get_graph()
    assert [n for n in graph.nodes if not n.startswith("__")] == list(NODES)
    edges = {(e.source, e.target) for e in graph.edges}
    chain = ["__start__", *NODES, "__end__"]
    assert edges == set(zip(chain, chain[1:], strict=False))


async def test_streams_retrieval_then_tokens_and_puts_numbered_context_in_the_prompt():
    h = Harness()
    events, summary, text = await h.run()
    kinds = [e["event"] for e in events]
    assert kinds[0] == "retrieval" and kinds[1] == "llm_started" and kinds[-1] == "llm_finished"
    assert text == "You said: Which port does Zephyr use?"
    assert summary["status"] == "ok" and summary["chunkCount"] == 1 and summary["sources"][0]["uri"] == "zephyr.md"
    prompt = h.llm.calls[-1]
    assert prompt[1].role == "system" and "[1] Zephyr (source: kb)" in prompt[1].content and "7777" in prompt[1].content
    assert len(h.llm.calls) == 1  # exactly one generation per turn


@pytest.mark.parametrize(
    ("kwargs", "state", "reason"),
    [
        ({"rag_enabled": False}, {}, "disabled"),
        ({}, {"retrieval": None}, "not_requested"),
        ({"configured": False}, {}, "embeddings_unconfigured"),
        ({"has_knowledge": False}, {}, "empty_knowledge_base"),
    ],
)
async def test_skip_paths_make_no_retrieval_call(kwargs, state, reason):
    h = Harness(**kwargs)
    _, summary, text = await h.run(**state)
    assert summary["status"] == "skipped" and summary["reason"] == reason
    assert h.factory_calls == 0  # no retriever, hence no embedding call
    assert h.llm.calls[-1][1].role == "user"  # no context message
    assert text


async def test_empty_retrieval_adds_no_context():
    h = Harness(documents=())
    _, summary, _ = await h.run()
    assert summary["status"] == "empty" and summary["sources"] == []
    assert [m.role for m in h.llm.calls[-1]] == ["system", "user"]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EmbeddingError("embedding_timeout"), "embedding_timeout"),
        (RetrievalError("database_unavailable"), "database_unavailable"),
        (RuntimeError("unexpected"), "internal_error"),
    ],
)
async def test_retrieval_failures_degrade_to_no_context(error, reason):
    h = Harness(error=error)
    _, summary, text = await h.run()
    assert summary["status"] == "failed" and summary["reason"] == reason
    assert text == "You said: Which port does Zephyr use?"
    assert [m.role for m in h.llm.calls[-1]] == ["system", "user"]


async def test_retrieval_timeout_is_bounded():
    h = Harness(delay=5, rag_retrieval_timeout_s=0.2)
    started = asyncio.get_running_loop().time()
    _, summary, _ = await h.run()
    assert summary["status"] == "failed" and summary["reason"] == "timeout"
    assert asyncio.get_running_loop().time() - started < 2


async def test_llm_errors_propagate_unchanged_and_are_not_retried():
    h = Harness(llm=FakeProvider(fail_before_first=LLMUnavailable("down")))
    with pytest.raises(LLMUnavailable):
        await h.run()
    assert len(h.llm.calls) == 1
    mid = Harness(llm=FakeProvider(fail_after=(2, LLMUnavailable("dropped"))))
    with pytest.raises(LLMUnavailable):
        await mid.run()
    assert len(mid.llm.calls) == 1 and mid.llm.closed_streams == 1


async def test_cancelling_the_consumer_stops_generation_and_closes_the_stream():
    llm = FakeProvider(reply=lambda m: " ".join(f"w{i}" for i in range(500)), token_delay_s=0.01)
    h = Harness(llm=llm)
    stream = h.graph.astream(h.state(), stream_mode="custom").__aiter__()
    tokens = 0
    while tokens < 5:
        if (await stream.__anext__())["event"] == "token":
            tokens += 1
    pending = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    await stream.aclose()
    produced = llm.emitted
    await asyncio.sleep(0.2)
    assert llm.emitted == produced < 500  # nothing generated after the cancel
    assert llm.closed_streams == 1 and len(llm.calls) == 1
