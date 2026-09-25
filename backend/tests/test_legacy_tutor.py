"""The tutor as it behaves before any per-student settings exist, frozen.

Per-student tutor settings add instructions to the system prompt. A student who has set
nothing must get exactly what every student gets today: the same system prompt, byte for
byte, and the same messages sent to the model. These fixtures were recorded from the code
before any settings existed; if one of these tests fails, the default tutor changed.
"""

import json
from pathlib import Path

from app.chat.assistant import SYSTEM_PROMPT, AssistantConfig, resolve_assistant_config
from app.rag.graph import RetrievalOptions
from tests.conftest import register, stream_chat

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_PROMPT = (FIXTURES / "legacy_system_prompt.txt").read_bytes().decode("utf-8")
LEGACY_MESSAGES = json.loads((FIXTURES / "legacy_llm_messages.json").read_bytes().decode("utf-8"))


def test_the_system_prompt_is_the_frozen_legacy_prompt():
    assert SYSTEM_PROMPT.encode("utf-8") == LEGACY_PROMPT.encode("utf-8")


def test_the_default_assistant_configuration_is_unchanged():
    assert resolve_assistant_config(None, None) == AssistantConfig(
        system_prompt=LEGACY_PROMPT, retrieval=RetrievalOptions(), model=None, temperature=None
    )


async def test_a_conversation_sends_the_model_exactly_the_legacy_messages(client, app, fake_llm):
    account = await register(client, app)
    _, first = await stream_chat(client, account["headers"], "What is photosynthesis?")
    conversation_id = first[0][1]["conversationId"]
    await stream_chat(client, account["headers"], "Explain the second step.", conversation_id)

    sent = [[{"role": m.role, "content": m.content} for m in call] for call in fake_llm.calls]
    assert sent == LEGACY_MESSAGES
