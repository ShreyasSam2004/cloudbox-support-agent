"""In-process sliding-window rate limiter.

Per-instance only: in AWS the WAF rate-based rule provides the distributed limit; this limiter
protects each task (and the LLM budget) even if WAF is misconfigured. Swap in a Redis-backed
implementation of the same interface for exact global limits.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, max_keys: int = 50_000) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)`` and record the hit if allowed."""
        now = time.monotonic()
        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(now)
                hits = deque()
                self._hits[key] = hits
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(self.window_s - (now - hits[0]), 0.0)
            hits.append(now)
            return True, 0.0

    def _evict(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window_s]
        for key in stale:
            del self._hits[key]
