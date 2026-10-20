"""PostgreSQL + pgvector integration tests.

Run against a real database: ``docker compose up -d postgres`` then
``DATABASE_URL=postgresql://cloudbox:cloudbox@localhost:5432/cloudbox uv run pytest -m integration``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from backend.retrieval.embeddings import HashingEmbedder
from backend.retrieval.ingestion import IngestionPipeline
from backend.retrieval.retriever import Retriever
from backend.retrieval.vector_store import IndexMismatchError, InMemoryVectorStore
from backend.schemas.domain import MetadataFilter
from backend.schemas.trace import AgentTrace
from backend.storage.customers import JsonCustomerRepository, PostgresCustomerRepository
from backend.storage.sessions import PostgresSessionStore, Session
from backend.storage.traces import PostgresTraceStore
from tests.conftest import DATA

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set"),
]


@pytest.fixture
async def pool() -> AsyncIterator[object]:
    from backend.storage.db import create_pool, run_migrations

    pool = await create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS kb_chunks, kb_documents, kb_index_meta CASCADE")
    await run_migrations(pool)
    yield pool
    await pool.close()


async def test_migrations_are_idempotent(pool) -> None:  # type: ignore[no-untyped-def]
    from backend.storage.db import run_migrations

    assert await run_migrations(pool) == []


async def test_pgvector_store_matches_in_memory_store(pool) -> None:  # type: ignore[no-untyped-def]
    from backend.retrieval.pgvector_store import PgVectorStore

    embedder = HashingEmbedder(256)
    pg = PgVectorStore(pool)
    report = await IngestionPipeline(pg, embedder).ingest_directory(DATA / "knowledge_base")
    assert report.documents_indexed == report.documents_seen
    assert await pg.chunk_count() == report.chunks_written

    memory = InMemoryVectorStore(None)
    await IngestionPipeline(memory, embedder).ingest_directory(DATA / "knowledge_base")

    query = "rotate API key grace period"
    vector = await embedder.embed_query(query)
    pg_dense = [c.chunk_id for c, _ in await pg.vector_search(vector, 5)]
    mem_dense = [c.chunk_id for c, _ in await memory.vector_search(vector, 5)]
    assert pg_dense[0] == mem_dense[0]  # HNSW is approximate; the top hit must agree

    hybrid = await Retriever(pg, embedder).search("quota_exceeded CBX-4292", 5)
    assert "api-rate-limits" in [c.chunk.doc_id for c in hybrid.chunks]
    filtered = await Retriever(pg, embedder).search("refund", 5, MetadataFilter(doc_types=["faq"]))
    assert {c.chunk.metadata["doc_type"] for c in filtered.chunks} == {"faq"}

    again = await IngestionPipeline(pg, embedder).ingest_directory(DATA / "knowledge_base")
    assert again.documents_indexed == 0
    with pytest.raises(IndexMismatchError):
        await pg.ensure_index("another-model", 256)


async def test_session_customer_and_trace_stores(pool) -> None:  # type: ignore[no-untyped-def]
    sessions = PostgresSessionStore(pool)
    session = Session(session_id=uuid.uuid4().hex, owner="o", bound_customer_id="C1002")
    session.add_user_turn("my id is C1002")
    await sessions.save(session)
    loaded = await sessions.get(session.session_id)
    assert loaded is not None and loaded.mentioned_customer_ids == ["C1002"]

    repo = PostgresCustomerRepository(pool)
    await repo.upsert_many(JsonCustomerRepository(DATA / "customers" / "customers.json").all())
    account = await repo.get("c1002")
    assert account is not None and account.subscription.status == "canceled"

    traces = PostgresTraceStore(pool)
    old = datetime(2020, 1, 1, tzinfo=UTC)  # older than any retention window
    trace = AgentTrace(
        execution_id="exec_" + uuid.uuid4().hex[:24], session_id=session.session_id, started_at=old
    )
    await traces.save(trace)
    assert (await traces.get(trace.execution_id)) is not None
    assert await traces.prune(timedelta(days=0)) >= 1
