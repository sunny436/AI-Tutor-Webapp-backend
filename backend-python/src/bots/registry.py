"""
bots/registry.py
----------------
The Bot Manager. One place that answers "which bot is this request for, and what
is that bot allowed to see?"

WHY THIS EXISTS
This backend is the central service for several frontends — Ayurveda today, more
later — all hitting the same `/consult`. The thing that must never happen is one
bot answering out of another bot's knowledge base. Before this module the
collection name was a module constant in `src/knowledge.py`, so "which corpus"
was not a question the code could even ask.

ISOLATION IS ENFORCED AT THE RETRIEVER, NOT IN THE PROMPT
`BotConfig.knowledge_collection` is passed down into the vector store lookup, so
a bot physically searches a different Chroma collection. Telling the model which
bot it is would not be isolation — it would be a request. The only way to reach
another bot's notes is to be configured with that collection.

ADDING A BOT LATER
Add one `BotConfig` to `BOTS`. Nothing else changes: the retriever already reads
the collection from here, and `get_bot` already rejects anything unregistered.
A new bot needs its own ingested Chroma collection — pointing two bots at one
collection would silently defeat this whole module.
"""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class BotConfig:
    """Everything that varies between bots on this backend.

    Frozen because it is shared across concurrent requests; a mutable config
    handed to a request handler is a cross-request leak waiting to happen.
    """

    # Stable identifier the frontend sends. Also the registry key.
    bot_id: str

    # THE ISOLATION BOUNDARY. The Chroma collection this bot's curated notes live
    # in. Two bots must never share one, and nothing outside this module should
    # hardcode it.
    knowledge_collection: str

    # Shown in logs and errors; never used for routing.
    display_name: str = ""

    # Per-bot scope on the external GraphRAG index. DECLARATIVE ONLY — nothing
    # reads this yet, and no GraphRAG client exists. It lives here now so that
    # adding the retriever later is one file under src/retrieval/ rather than a
    # change to the bot boundary as well.
    graphrag_project_id: str = ""


class UnknownBotError(ValueError):
    """Raised for a bot_id that is not registered.

    Deliberately NOT a fallback to the default bot. Silently serving Ayurveda's
    corpus to a caller that asked for something else is precisely the leak this
    module exists to prevent, and it would pass every test that only ever checks
    the happy path.
    """

    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        super().__init__(f"unknown bot_id: {bot_id!r}")


DEFAULT_BOT_ID = "ayurveda"

BOTS: dict[str, BotConfig] = {
    "ayurveda": BotConfig(
        bot_id="ayurveda",
        # EXACTLY today's value. This string was `COLLECTION_NAME` in
        # src/knowledge.py; moving it here is what makes the corpus a property of
        # the bot rather than of the module. Changing it repoints the live bot at
        # an empty collection, so treat it as data, not as a tunable.
        knowledge_collection="ayurveda_yoga",
        display_name="Ayurveda & Yoga",
        graphrag_project_id=config.GRAPHRAG_PROJECT_ID,
    ),
}


def get_bot(bot_id: str | None) -> BotConfig:
    """Resolve a bot_id to its config.

    Absent or empty -> the default bot. This is TRANSITIONAL: the current
    frontend does not send `bot_id` yet, and defaulting is what keeps the live
    site behaving exactly as it does today. Once the frontend sends it, absence
    should become an error too — a default is a silent fallback wearing a
    different hat, and it is only tolerable while there is exactly one bot.

    Unregistered -> UnknownBotError. Never a fallback.
    """
    if not bot_id:
        return BOTS[DEFAULT_BOT_ID]

    bot = BOTS.get(bot_id)
    if bot is None:
        raise UnknownBotError(bot_id)
    return bot
