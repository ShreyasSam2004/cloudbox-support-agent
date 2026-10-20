"""Customer account repository (stand-in for the billing/CRM system of record)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import asyncpg

from backend.schemas.domain import CustomerAccount


class CustomerRepository(Protocol):
    async def get(self, customer_id: str) -> CustomerAccount | None: ...


class JsonCustomerRepository:
    def __init__(self, path: Path) -> None:
        records = json.loads(path.read_text(encoding="utf-8"))
        self._accounts = {r["customer_id"].upper(): CustomerAccount.model_validate(r) for r in records}

    async def get(self, customer_id: str) -> CustomerAccount | None:
        return self._accounts.get(customer_id.upper())

    def all(self) -> list[CustomerAccount]:
        return list(self._accounts.values())


class PostgresCustomerRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, customer_id: str) -> CustomerAccount | None:
        row = await self._pool.fetchrow(
            "SELECT data FROM customers WHERE customer_id = $1", customer_id.upper()
        )
        if row is None:
            return None
        data = row["data"]
        return CustomerAccount.model_validate(json.loads(data) if isinstance(data, str) else data)

    async def upsert_many(self, accounts: list[CustomerAccount]) -> int:
        await self._pool.executemany(
            """
            INSERT INTO customers (customer_id, data, updated_at) VALUES ($1, $2::jsonb, now())
            ON CONFLICT (customer_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
            """,
            [(a.customer_id.upper(), a.model_dump_json()) for a in accounts],
        )
        return len(accounts)
