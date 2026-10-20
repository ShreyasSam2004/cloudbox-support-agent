"""Async retry with capped exponential backoff and full jitter.

Used by the tool registry and by providers that do not ship their own retry logic.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

_rng = secrets.SystemRandom()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 4.0

    def backoff(self, attempt: int) -> float:
        """Full-jitter delay before retry number ``attempt`` (1-based)."""
        ceiling = min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
        return _rng.uniform(0, ceiling)


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    is_retryable: Callable[[BaseException], bool],
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> tuple[T, int]:
    """Run ``fn`` until it succeeds, fails with a non-retryable error, or attempts run out.

    Returns ``(result, attempts_used)``. The last exception is re-raised on exhaustion.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn(), attempt
        except Exception as exc:
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            delay = policy.backoff(attempt)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            await asyncio.sleep(delay)
