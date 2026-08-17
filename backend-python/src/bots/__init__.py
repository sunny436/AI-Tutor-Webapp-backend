"""Bot Manager — per-bot configuration and the knowledge isolation boundary."""

from src.bots.registry import (
    BOTS,
    DEFAULT_BOT_ID,
    BotConfig,
    UnknownBotError,
    get_bot,
)

__all__ = [
    "BOTS",
    "DEFAULT_BOT_ID",
    "BotConfig",
    "UnknownBotError",
    "get_bot",
]
