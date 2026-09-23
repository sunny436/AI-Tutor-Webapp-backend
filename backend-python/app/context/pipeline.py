"""Run context providers concurrently; a slow or failing provider never fails the chat turn."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.context.base import ContextBlock, ContextProvider, ContextRequest
from app.logging import get_logger

log = get_logger("app.context")


class ContextPipeline:
    def __init__(self, providers: Sequence[ContextProvider], timeout_s: float) -> None:
        self.providers = list(providers)
        self.timeout_s = timeout_s

    async def gather(self, request: ContextRequest) -> list[ContextBlock]:
        if not self.providers:
            return []
        results = await asyncio.gather(*(self._safe(p, request) for p in self.providers))
        return [block for blocks in results for block in blocks]

    async def _safe(self, provider: ContextProvider, request: ContextRequest) -> list[ContextBlock]:
        try:
            return list(await asyncio.wait_for(provider.provide(request), timeout=self.timeout_s))
        except TimeoutError:
            log.warning("context provider timed out", extra={"provider": provider.name})
        except Exception as error:  # noqa: BLE001 - context is an enhancement, never a failure
            log.warning(
                "context provider failed", extra={"provider": provider.name, "error_type": type(error).__name__}
            )
        return []


def render_context(blocks: Sequence[ContextBlock]) -> str:
    """Context as one system message. Empty string when there is none."""
    if not blocks:
        return ""
    lines = ["Use the following reference material when it is relevant to the user's request:"]
    for index, block in enumerate(blocks, start=1):
        lines.append(f"[{index}] (source: {block.source})\n{block.text}")
    return "\n\n".join(lines)
