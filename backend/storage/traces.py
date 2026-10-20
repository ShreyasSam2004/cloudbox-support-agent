"""Persistence for agent execution traces (inspectable trajectories)."""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Protocol

import asyncpg

from backend.schemas.trace import AgentTrace


class TraceStore(Protocol):
    async def save(self, trace: AgentTrace) -> None: ...

    async def get(self, execution_id: str) -> AgentTrace | None: ...

    async def prune(self, older_than: timedelta) -> int: ...


class InMemoryTraceStore:
    def __init__(self, capacity: int = 500) -> None:
        self._traces: OrderedDict[str, AgentTrace] = OrderedDict()
        self._capacity = capacity

    async def save(self, trace: AgentTrace) -> None:
        self._traces[trace.execution_id] = trace
        self._traces.move_to_end(trace.execution_id)
        while len(self._traces) > self._capacity:
            self._traces.popitem(last=False)

    async def get(self, execution_id: str) -> AgentTrace | None:
        return self._traces.get(execution_id)

    async def prune(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        stale = [k for k, t in self._traces.items() if t.started_at < cutoff]
        for key in stale:
            del self._traces[key]
        return len(stale)


class PostgresTraceStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, trace: AgentTrace) -> None:
        await self._pool.execute(
            """
            INSERT INTO agent_traces (execution_id, session_id, request_id, created_at, data)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
            """,
            trace.execution_id,
            trace.session_id,
            trace.request_id,
            trace.started_at,
            trace.model_dump_json(),
        )

    async def get(self, execution_id: str) -> AgentTrace | None:
        row = await self._pool.fetchrow("SELECT data FROM agent_traces WHERE execution_id = $1", execution_id)
        if row is None:
            return None
        data = row["data"]
        return AgentTrace.model_validate(json.loads(data) if isinstance(data, str) else data)

    async def prune(self, older_than: timedelta) -> int:
        result = await self._pool.execute(
            "DELETE FROM agent_traces WHERE created_at < $1", datetime.now(UTC) - older_than
        )
        return int(str(result).split()[-1])
