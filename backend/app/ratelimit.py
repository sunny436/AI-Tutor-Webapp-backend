"""A per-key sliding-window limit, kept in this process's memory.

For endpoints that only compute (no database writes, no email): a database row per request,
as sign-in throttling keeps in auth_attempts, would cost more than the work it protects. The
API runs as one process, so one counter per process is one counter; with several processes
each would allow the limit, which is acceptable for these cheap endpoints.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    MAX_KEYS = 10_000  # forget idle keys beyond this, so memory stays bounded

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > self.MAX_KEYS:
            self._forget_idle(now)
        return True

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self.window_s]:
            del self._hits[key]
