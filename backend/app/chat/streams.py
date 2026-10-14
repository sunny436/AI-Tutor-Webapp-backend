"""Server-Sent Events encoding and the registry of in-flight generations.

Each generation runs in its own task, independent of the HTTP connection, so its
result is always persisted. The registry lets the cancel endpoint and client
disconnects stop it promptly; PostgreSQL remains the source of truth for status.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class ChatEvent:
    type: str  # meta | token | done | error
    data: dict


def encode_sse(event: ChatEvent) -> bytes:
    return f"event: {event.type}\ndata: {json.dumps(event.data, default=str, ensure_ascii=False)}\n\n".encode()


@dataclass
class Generation:
    message_id: uuid.UUID
    queue: asyncio.Queue
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    last_db_check: float = 0.0


class ActiveGenerations:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Generation] = {}

    def add(self, generation: Generation) -> None:
        self._items[generation.message_id] = generation

    def remove(self, message_id: uuid.UUID) -> None:
        self._items.pop(message_id, None)

    def cancel(self, message_id: uuid.UUID) -> bool:
        generation = self._items.get(message_id)
        if generation is None:
            return False
        generation.cancel.set()
        return True

    async def shutdown(self, timeout_s: float = 5.0) -> None:
        """Stop every generation and wait briefly so each one persists its result."""
        tasks = []
        for generation in list(self._items.values()):
            generation.cancel.set()
            if generation.task is not None:
                tasks.append(generation.task)
        if tasks:
            await asyncio.wait(tasks, timeout=timeout_s)


async def sse_body(first: ChatEvent, generation: Generation, keepalive_s: float) -> AsyncIterator[bytes]:
    """The HTTP body: meta, then events as they are produced, with keepalive comments.

    If the client goes away before the generation finishes, that is treated as a
    stop: the generation is cancelled and persists what it has as `cancelled`.
    """
    finished = False
    try:
        yield b": open\n\n"
        yield encode_sse(first)
        while True:
            try:
                event = await asyncio.wait_for(generation.queue.get(), timeout=keepalive_s)
            except TimeoutError:
                yield b": keepalive\n\n"
                continue
            if event is None:
                finished = True
                return
            yield encode_sse(event)
    finally:
        if not finished:
            generation.cancel.set()
