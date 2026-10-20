"""PostgreSQL + pgvector store (production).

* Dense retrieval: ``vector(d)`` column with an HNSW index (cosine distance).
* Lexical retrieval: a generated ``tsvector`` column with a GIN index, queried with an OR-query
  built from the same tokenizer as the in-process BM25 (support queries rarely share *all* terms
  with the answer, so AND semantics would miss most of them).
* The embedding model and dimension the index was built with are recorded in ``kb_index_meta``;
  serving refuses to mix models (a classic silent-quality-regression bug).
"""

from __future__ import annotations

import json
import re
from typing import Any

import asyncpg

from backend.retrieval.bm25 import tokenize
from backend.retrieval.vector_store import IndexMismatchError
from backend.schemas.domain import ChunkRecord, DocumentRecord, MetadataFilter

_SAFE_LEXEME = re.compile(r"^[a-z0-9]+$")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def _or_tsquery(query: str) -> str:
    lexemes: list[str] = []
    for token in tokenize(query):
        for part in re.split(r"[-_]", token):
            if _SAFE_LEXEME.match(part) and part not in lexemes:
                lexemes.append(part)
    return " | ".join(lexemes)


def _row_to_chunk(row: asyncpg.Record) -> ChunkRecord:
    metadata = row["metadata"]
    return ChunkRecord(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        title=row["title"],
        section_path=row["section_path"],
        content=row["content"],
        embedding_text=row["embedding_text"],
        ordinal=row["ordinal"],
        metadata=json.loads(metadata) if isinstance(metadata, str) else dict(metadata),
    )


def _filter_args(flt: MetadataFilter | None) -> tuple[list[str] | None, list[str] | None]:
    if flt is None:
        return None, None
    return flt.doc_ids or None, flt.doc_types or None


class PgVectorStore:
    def __init__(self, pool: asyncpg.Pool, ef_search: int = 80) -> None:
        self._pool = pool
        self._ef_search = ef_search

    async def ensure_index(self, embedding_model: str, dim: int) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(724001)")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_index_meta (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    embedding_model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            meta = await conn.fetchrow("SELECT embedding_model, dim FROM kb_index_meta WHERE id = 1")
            if meta is not None and (meta["embedding_model"], meta["dim"]) != (embedding_model, dim):
                raise IndexMismatchError(
                    f"index built with {meta['embedding_model']} (dim {meta['dim']}), configured "
                    f"{embedding_model} (dim {dim}); drop kb_chunks and re-ingest"
                )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            # dim is an int validated by the caller's settings; DDL cannot take bind parameters.
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL REFERENCES kb_documents(doc_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    section_path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding_text TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embedding_text)) STORED,
                    embedding VECTOR({int(dim)}) NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw "
                "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS kb_chunks_tsv_gin ON kb_chunks USING gin (tsv)")
            await conn.execute("CREATE INDEX IF NOT EXISTS kb_chunks_doc_id ON kb_chunks (doc_id)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS kb_chunks_doc_type ON kb_chunks ((metadata->>'doc_type'))"
            )
            await conn.execute(
                """
                INSERT INTO kb_index_meta (id, embedding_model, dim) VALUES (1, $1, $2)
                ON CONFLICT (id) DO NOTHING
                """,
                embedding_model,
                dim,
            )

    async def document_hashes(self) -> dict[str, str]:
        rows = await self._pool.fetch("SELECT doc_id, content_hash FROM kb_documents")
        return {r["doc_id"]: r["content_hash"] for r in rows}

    async def upsert_document(
        self, doc: DocumentRecord, chunks: list[ChunkRecord], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO kb_documents (doc_id, title, doc_type, source_path, content_hash, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (doc_id) DO UPDATE SET
                    title = EXCLUDED.title, doc_type = EXCLUDED.doc_type,
                    source_path = EXCLUDED.source_path, content_hash = EXCLUDED.content_hash,
                    metadata = EXCLUDED.metadata, ingested_at = now()
                """,
                doc.doc_id,
                doc.title,
                doc.doc_type,
                doc.source_path,
                doc.content_hash,
                json.dumps(doc.metadata, default=str),
            )
            await conn.execute("DELETE FROM kb_chunks WHERE doc_id = $1", doc.doc_id)
            await conn.executemany(
                """
                INSERT INTO kb_chunks (chunk_id, doc_id, ordinal, title, section_path, content,
                                       embedding_text, metadata, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::vector)
                """,
                [
                    (
                        c.chunk_id,
                        c.doc_id,
                        c.ordinal,
                        c.title,
                        c.section_path,
                        c.content,
                        c.embedding_text,
                        json.dumps(c.metadata, default=str),
                        _vector_literal(e),
                    )
                    for c, e in zip(chunks, embeddings, strict=True)
                ],
            )

    async def delete_documents(self, doc_ids: list[str]) -> None:
        if doc_ids:
            await self._pool.execute("DELETE FROM kb_documents WHERE doc_id = ANY($1::text[])", doc_ids)

    async def list_documents(self) -> list[DocumentRecord]:
        rows = await self._pool.fetch(
            "SELECT doc_id, title, doc_type, source_path, content_hash, metadata FROM kb_documents ORDER BY doc_id"
        )
        out: list[DocumentRecord] = []
        for r in rows:
            meta: Any = r["metadata"]
            out.append(
                DocumentRecord(
                    doc_id=r["doc_id"],
                    title=r["title"],
                    doc_type=r["doc_type"],
                    source_path=r["source_path"],
                    content_hash=r["content_hash"],
                    metadata=json.loads(meta) if isinstance(meta, str) else dict(meta),
                )
            )
        return out

    async def vector_search(
        self, embedding: list[float], k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]:
        doc_ids, doc_types = _filter_args(flt)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}")
            rows = await conn.fetch(
                """
                SELECT chunk_id, doc_id, ordinal, title, section_path, content, embedding_text, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM kb_chunks
                WHERE ($2::text[] IS NULL OR doc_id = ANY($2::text[]))
                  AND ($3::text[] IS NULL OR metadata->>'doc_type' = ANY($3::text[]))
                ORDER BY embedding <=> $1::vector
                LIMIT $4
                """,
                _vector_literal(embedding),
                doc_ids,
                doc_types,
                k,
            )
        return [(_row_to_chunk(r), float(r["score"])) for r in rows]

    async def lexical_search(
        self, query: str, k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]:
        tsquery = _or_tsquery(query)
        if not tsquery:
            return []
        doc_ids, doc_types = _filter_args(flt)
        rows = await self._pool.fetch(
            """
            SELECT chunk_id, doc_id, ordinal, title, section_path, content, embedding_text, metadata,
                   ts_rank_cd(tsv, q) AS score
            FROM kb_chunks, to_tsquery('english', $1) AS q
            WHERE tsv @@ q
              AND ($2::text[] IS NULL OR doc_id = ANY($2::text[]))
              AND ($3::text[] IS NULL OR metadata->>'doc_type' = ANY($3::text[]))
            ORDER BY score DESC
            LIMIT $4
            """,
            tsquery,
            doc_ids,
            doc_types,
            k,
        )
        return [(_row_to_chunk(r), float(r["score"])) for r in rows]

    async def chunk_count(self) -> int:
        value = await self._pool.fetchval("SELECT count(*) FROM kb_chunks")
        return int(value or 0)
