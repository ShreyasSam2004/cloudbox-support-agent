"""Conversation/session state.

A session holds the *conversation* (user messages and final assistant answers) plus a few facts
the agent needs across turns (bound customer, customer IDs the user typed). It deliberately does
**not** store tool traces or retrieved passages — those live in the execution trace — so the
context sent to the model stays small and the session never accumulates untrusted content.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import asyncpg
from pydantic import BaseModel, Field

MAX_STORED_TURNS = 50
_CUSTOMER_ID_RE = re.compile(r"\bC\d{3,6}\b", re.I)


def extract_customer_ids(text: str) -> list[str]:
    return sorted({m.upper() for m in _CUSTOMER_ID_RE.findall(text)})


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    response_type: str | None = None
    source_titles: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Session(BaseModel):
    session_id: str
    owner: str
    bound_customer_id: str | None = None
    mentioned_customer_ids: list[str] = Field(default_factory=list)
    last_account_lookup: str | None = None
    turns: list[Turn] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_user_turn(self, text: str) -> None:
        self.turns.append(Turn(role="user", content=text))
        for cid in extract_customer_ids(text):
            if cid not in self.mentioned_customer_ids:
                self.mentioned_customer_ids.append(cid)
        self._trim()

    def add_assistant_turn(self, text: str, response_type: str, source_titles: list[str]) -> None:
        self.turns.append(
            Turn(role="assistant", content=text, response_type=response_type, source_titles=source_titles)
        )
        self._trim()

    def _trim(self) -> None:
        self.turns = self.turns[-MAX_STORED_TURNS:]
        self.updated_at = datetime.now(UTC)


class SessionStore(Protocol):
    async def get(self, session_id: str) -> Session | None: ...

    async def save(self, session: Session) -> None: ...

    async def prune(self, older_than: timedelta) -> int: ...


class InMemorySessionStore:
    def __init__(self, max_sessions: int = 10_000) -> None:
        self._sessions: dict[str, Session] = {}
        self._max = max_sessions

    async def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        return session.model_copy(deep=True) if session else None

    async def save(self, session: Session) -> None:
        if len(self._sessions) >= self._max and session.session_id not in self._sessions:
            oldest = min(self._sessions.values(), key=lambda s: s.updated_at)
            del self._sessions[oldest.session_id]
        self._sessions[session.session_id] = session.model_copy(deep=True)

    async def prune(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        stale = [sid for sid, s in self._sessions.items() if s.updated_at < cutoff]
        for sid in stale:
            del self._sessions[sid]
        return len(stale)


class PostgresSessionStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, session_id: str) -> Session | None:
        row = await self._pool.fetchrow("SELECT data FROM sessions WHERE session_id = $1", session_id)
        if row is None:
            return None
        data = row["data"]
        return Session.model_validate(json.loads(data) if isinstance(data, str) else data)

    async def save(self, session: Session) -> None:
        await self._pool.execute(
            """
            INSERT INTO sessions (session_id, owner, bound_customer_id, data, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            ON CONFLICT (session_id) DO UPDATE SET
                bound_customer_id = EXCLUDED.bound_customer_id,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at
            """,
            session.session_id,
            session.owner,
            session.bound_customer_id,
            session.model_dump_json(),
            session.created_at,
            session.updated_at,
        )

    async def prune(self, older_than: timedelta) -> int:
        result = await self._pool.execute(
            "DELETE FROM sessions WHERE updated_at < $1", datetime.now(UTC) - older_than
        )
        return int(str(result).split()[-1])
