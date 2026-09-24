"""The deterministic prompt budget (pure unit tests, no database)."""

from langchain_core.documents import Document

from app.llm.base import ChatMessage
from app.rag.context import CONTEXT_HEADER, build_llm_messages

SYSTEM = "S" * 100


def doc(n, size=100, score=0.9):
    return Document(
        page_content=f"chunk{n} " + "x" * (size - 7),
        metadata={
            "chunk_id": f"c{n}",
            "document_id": f"d{n}",
            "source_id": "s",
            "source": "kb",
            "title": f"T{n}",
            "uri": f"u{n}.md",
            "ordinal": 0,
            "score": score,
        },
    )


def convo(*texts):
    return [ChatMessage("user" if i % 2 == 0 else "assistant", t) for i, t in enumerate(texts)]


def test_system_and_latest_message_always_kept_even_over_budget():
    out = build_llm_messages(
        SYSTEM, convo("old", "reply", "L" * 5000), [doc(1)], max_input_chars=10, max_context_chars=10
    )
    assert [m.role for m in out.messages] == ["system", "user"]
    assert out.messages[-1].content == "L" * 5000 and out.sources == [] and out.history_dropped == 2


def test_context_whole_chunks_in_rank_order_numbered_like_sources():
    docs = [doc(1), doc(2), doc(3)]
    budget = len(CONTEXT_HEADER) + 2 * 130  # room for two blocks, not three
    out = build_llm_messages(SYSTEM, convo("q"), docs, max_input_chars=100_000, max_context_chars=budget)
    context = out.messages[1].content
    assert out.messages[1].role == "system" and context.startswith(CONTEXT_HEADER)
    assert "[1] T1 (source: kb)" in context and "[2] T2 (source: kb)" in context and "[3]" not in context
    assert [s["chunkId"] for s in out.sources] == ["c1", "c2"]  # [n] maps to sources[n-1]
    assert "chunk3" not in context  # the chunk that did not fit is dropped whole, never cut


def test_history_newest_first_whole_messages_and_starts_with_user():
    history = convo("u1" * 50, "a1" * 50, "u2" * 50, "a2" * 50, "latest")  # earlier messages: 100 chars each
    # budget fits system + latest + the two most recent earlier messages only
    budget = len(SYSTEM) + len("latest") + 2 * 100
    out = build_llm_messages(SYSTEM, history, [], max_input_chars=budget, max_context_chars=0)
    kept = [m.content[:2] for m in out.messages[1:]]
    # newest-first gives [u2, a2]; it already starts with a user message
    assert kept == ["u2", "a2", "la"] and out.history_kept == 2 and out.history_dropped == 2
    # with room for only one earlier message (an assistant turn), it is dropped too
    out = build_llm_messages(SYSTEM, history, [], max_input_chars=budget - 50, max_context_chars=0)
    assert [m.role for m in out.messages] == ["system", "user"]


def test_no_documents_means_no_context_message_and_is_deterministic():
    a = build_llm_messages(SYSTEM, convo("hi", "hello", "q"), [], max_input_chars=1000, max_context_chars=500)
    b = build_llm_messages(SYSTEM, convo("hi", "hello", "q"), [], max_input_chars=1000, max_context_chars=500)
    assert [m.role for m in a.messages] == ["system", "user", "assistant", "user"]
    assert a == b and a.context_chars == 0 and a.sources == []
