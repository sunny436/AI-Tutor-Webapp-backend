"""The tutor as it behaves before any per-student settings exist, frozen.

Per-student tutor settings add instructions to the system prompt. A student who has set
nothing and not learnt yet must get exactly what every student got before settings existed: the
same system prompt, byte for byte, and the same messages sent to the model. Once they have
learnt, a "Learning so far" line follows the prompt (owner decision, 2026-09-29). These fixtures
were recorded from the code before any settings existed; if one of these tests fails, the default
tutor changed. 2026-09-30: the owner asked for study formatting (cards, chemistry, diagrams, charts,
citations), so the prompt fixtures were re-recorded with that prompt (app/chat/assistant.py).
"""

import json
from pathlib import Path

from app.chat.assistant import SYSTEM_PROMPT, AssistantConfig, resolve_assistant_config
from app.learning.tutor import ABOUT_HEADING
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
    assert sent[0] == LEGACY_MESSAGES[0]
    # The second turn: the same messages, the prompt followed by how the student is doing.
    assert sent[1][1:] == LEGACY_MESSAGES[1][1:]
    progress = "- Learning so far: a 1-day learning streak; today 1 question"
    assert sent[1][0] == {"role": "system", "content": f"{LEGACY_PROMPT}\n\n{ABOUT_HEADING}\n{progress}"}
