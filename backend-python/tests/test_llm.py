"""The LLM layer: the real OpenAI-compatible provider against scripted HTTP, and fallback rules."""

import json

import httpx
import pytest

from app.llm.base import (
    ChatMessage,
    GenerationOptions,
    LLMAuthError,
    LLMBadRequest,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from app.llm.fake import FakeProvider
from app.llm.fallback import FallbackProvider
from app.llm.openai_compatible import OpenAICompatibleProvider

PROMPT = [ChatMessage("user", "hi")]
OPTS = GenerationOptions()


def sse_body(chunks: list[dict]) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


def chunk(content=None, finish=None, role=None, usage=None):
    delta = {}
    if role:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    body = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        body["choices"] = []
        body["usage"] = usage
    return body


def provider(handler, **kwargs) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        name="p", base_url="http://llm.test/v1", api_key="k", model="m", http_client=client, **kwargs
    )


async def collect(stream):
    return [p async for p in stream.parts]


async def test_openai_compatible_streams_text_and_usage():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body(
                [
                    chunk(role="assistant", content=""),
                    chunk(content="Hel"),
                    chunk(content="lo"),
                    chunk(finish="stop"),
                    chunk(usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
                ]
            ),
        )

    stream = await provider(handler).stream(PROMPT, OPTS)
    parts = await collect(stream)
    assert "".join(p.text for p in parts) == "Hello"
    assert parts[-1].usage.input_tokens == 5 and parts[-1].usage.output_tokens == 2
    assert any(p.finish_reason == "stop" for p in parts)
    assert seen["body"]["stream"] is True and seen["body"]["stream_options"] == {"include_usage": True}
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["auth"] == "Bearer k"
    assert stream.info.name == "p" and stream.info.model == "m"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LLMAuthError),
        (403, LLMAuthError),
        (404, LLMUnavailable),
        (402, LLMUnavailable),
        (429, LLMRateLimited),
        (400, LLMBadRequest),
        (500, LLMUnavailable),
        (503, LLMUnavailable),
    ],
)
async def test_http_errors_map_to_typed_errors(status, expected):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "vendor detail"}})

    with pytest.raises(expected):
        await provider(handler).stream(PROMPT, OPTS)


async def test_connection_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMUnavailable):
        await provider(handler).stream(PROMPT, OPTS)


async def test_missing_api_key_is_auth_error():
    p = OpenAICompatibleProvider(name="p", base_url="http://llm.test/v1", api_key="", model="m")
    with pytest.raises(LLMAuthError):
        await p.stream(PROMPT, OPTS)


async def test_fallback_used_before_first_token():
    primary = FakeProvider("primary", fail_before_first=LLMUnavailable("down"))
    secondary = FakeProvider("secondary")
    stream = await FallbackProvider([primary, secondary]).stream(PROMPT, OPTS)
    assert stream.info.name == "secondary"
    assert "".join(p.text for p in await collect(stream)) == "You said: hi"


async def test_fallback_on_auth_error_but_not_on_bad_request():
    ok = FakeProvider("secondary")
    stream = await FallbackProvider([FakeProvider("a", fail_before_first=LLMAuthError("x")), ok]).stream(PROMPT, OPTS)
    assert stream.info.name == "secondary"
    with pytest.raises(LLMBadRequest):
        await FallbackProvider([FakeProvider("a", fail_before_first=LLMBadRequest("x")), ok]).stream(PROMPT, OPTS)


async def test_no_fallback_after_first_token():
    primary = FakeProvider("primary", fail_after=(1, LLMTimeout("stalled")))
    secondary = FakeProvider("secondary")
    stream = await FallbackProvider([primary, secondary]).stream(PROMPT, OPTS)
    assert stream.info.name == "primary"
    with pytest.raises(LLMTimeout):
        await collect(stream)
    assert secondary.calls == []


async def test_all_providers_failing_raises_last_error():
    with pytest.raises(LLMRateLimited):
        await FallbackProvider(
            [
                FakeProvider("a", fail_before_first=LLMUnavailable("x")),
                FakeProvider("b", fail_before_first=LLMRateLimited("y")),
            ]
        ).stream(PROMPT, OPTS)


async def test_fallback_end_to_end_through_chat():
    from app.auth.emails import MemoryEmailSender
    from app.db.models import Message
    from app.main import create_app
    from tests.conftest import make_settings, register, stream_chat

    llm = FallbackProvider(
        [FakeProvider("ollima", fail_before_first=LLMUnavailable("down")), FakeProvider("openrouter")]
    )
    app = create_app(make_settings(), llm=llm, email_sender=MemoryEmailSender())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            account = await register(client, app)
            _, events = await stream_chat(client, account["headers"], "hi")
            assert events[-1][0] == "done" and events[-1][1]["message"]["content"] == "You said: hi"
            async with app.state.db.sessionmaker() as s:
                msg = await s.get(Message, events[-1][1]["message"]["id"])
            assert msg.metadata_["provider"] == "openrouter"


def test_provider_error_details_are_redacted():
    from app.llm.openai_compatible import map_error

    leaked = map_error(RuntimeError("Incorrect API key provided: sk-proj-abcdefghijklmnopqrstuvwxyz123456"))
    assert "abcdefghijklmnopqrstuvwxyz" not in str(leaked) and "[redacted]" in str(leaked)
