"""Injectable clock so the agent's notion of "today" is reproducible in tests and evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at if at.tzinfo else at.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._at
