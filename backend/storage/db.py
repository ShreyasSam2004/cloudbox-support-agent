"""PostgreSQL connection pool and a minimal, idempotent migration runner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import asyncpg

from backend.config.settings import Settings
from backend.observability.logging import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def create_pool(
    dsn: str,
    min_size: int = 1,
    max_size: int = 10,
    *,
    entra_token_scope: str | None = None,
    azure_client_id: str | None = None,
) -> asyncpg.Pool:
    """Create the pool. With ``entra_token_scope`` the password is a fresh Entra ID access token for the
    managed identity, fetched per connection (tokens expire; asyncpg calls the provider on every connect)."""
    password: Any = None
    if entra_token_scope is not None:
        from backend.models.azure_auth import token_provider

        password = token_provider(entra_token_scope, azure_client_id)
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=min_size, max_size=max_size, command_timeout=15, password=password
    )
    if pool is None:  # pragma: no cover - asyncpg returns None only for misuse
        raise RuntimeError("failed to create database pool")
    return pool


async def create_pool_from_settings(settings: Settings) -> asyncpg.Pool:
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required for Postgres-backed stores")
    return await create_pool(
        settings.database_url.get_secret_value(),
        settings.db_pool_min,
        settings.db_pool_max,
        entra_token_scope=settings.database_token_scope if settings.database_auth == "entra" else None,
        azure_client_id=settings.azure_client_id,
    )


async def run_migrations(pool: asyncpg.Pool, directory: Path = MIGRATIONS_DIR) -> list[str]:
    applied_now: list[str] = []
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(724000)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        migrations = await asyncio.to_thread(
            lambda: [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.sql"))]
        )
        for version, sql in migrations:
            if version in done:
                continue
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            applied_now.append(version)
            log.info("db.migration_applied", version=version)
    return applied_now
