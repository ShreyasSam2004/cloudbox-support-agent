"""Ingestion pipeline: load → parse → chunk → embed → upsert.

Idempotent: a document is re-embedded only when its content hash changes. The hash covers the
file content, the chunker version and size limit, and the embedding model, so changing any of
them re-indexes.
Documents removed from the source directory are deleted from the index.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.observability.logging import get_logger
from backend.retrieval.chunking import CHUNKER_VERSION, DEFAULT_MAX_CHARS, chunk_document
from backend.retrieval.embeddings import Embedder
from backend.retrieval.parsing import parse_markdown
from backend.retrieval.vector_store import VectorStore
from backend.schemas.domain import ChunkRecord, DocumentRecord

log = get_logger(__name__)

_REQUIRED_META = ("doc_id", "title", "doc_type")
_PROPAGATED_META = (
    "doc_type",
    "category",
    "authority",
    "effective_date",
    "version",
    "audience",
    "url",
    "plans",
    "supersedes",
)


@dataclass
class IngestionReport:
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_unchanged: int = 0
    documents_deleted: int = 0
    chunks_written: int = 0
    errors: list[str] = field(default_factory=list)


def _content_hash(raw: str, embedding_model: str, max_chars: int) -> str:
    digest = hashlib.sha256()
    for part in (raw, CHUNKER_VERSION, str(max_chars), embedding_model):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def build_records(
    raw: str, source_path: str, embedding_model: str, *, max_chars: int = DEFAULT_MAX_CHARS
) -> tuple[DocumentRecord, list[ChunkRecord]]:
    parsed = parse_markdown(raw)
    meta: dict[str, Any] = parsed.meta
    missing = [k for k in _REQUIRED_META if not meta.get(k)]
    if missing:
        raise ValueError(f"{source_path}: missing front matter fields {missing}")
    doc_id = str(meta["doc_id"])
    doc_meta = {k: (str(meta[k]) if k != "plans" else meta[k]) for k in _PROPAGATED_META if k in meta}
    document = DocumentRecord(
        doc_id=doc_id,
        title=str(meta["title"]),
        doc_type=str(meta["doc_type"]),
        source_path=source_path,
        content_hash=_content_hash(raw, embedding_model, max_chars),
        metadata=doc_meta,
    )
    chunks = [
        ChunkRecord(
            chunk_id=f"{doc_id}::{i:03d}",
            doc_id=doc_id,
            title=document.title,
            section_path=" > ".join(draft.section_path),
            content=draft.content,
            embedding_text=draft.embedding_text,
            ordinal=i,
            metadata={
                **doc_meta,
                "anchor": draft.anchor,
                "block_kinds": draft.block_kinds,
                "references": draft.references,
            },
        )
        for i, draft in enumerate(chunk_document(parsed, max_chars=max_chars))
    ]
    return document, chunks


class IngestionPipeline:
    def __init__(self, store: VectorStore, embedder: Embedder, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.store = store
        self.embedder = embedder
        self.max_chars = max_chars

    async def ingest_directory(self, source_dir: Path, *, force: bool = False) -> IngestionReport:
        report = IngestionReport()
        await self.store.ensure_index(self.embedder.model, self.embedder.dim)
        existing = await self.store.document_hashes()
        seen: set[str] = set()

        paths = await asyncio.to_thread(lambda: sorted(source_dir.glob("*.md")))
        for path in paths:
            report.documents_seen += 1
            raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
            try:
                document, chunks = build_records(
                    raw, path.as_posix(), self.embedder.model, max_chars=self.max_chars
                )
            except ValueError as exc:
                report.errors.append(str(exc))
                log.error("ingestion.parse_failed", path=str(path), error=str(exc))
                continue
            if document.doc_id in seen:
                report.errors.append(f"duplicate doc_id {document.doc_id} in {path}")
                continue
            seen.add(document.doc_id)

            if not force and existing.get(document.doc_id) == document.content_hash:
                report.documents_unchanged += 1
                continue
            embeddings = await self.embedder.embed_documents([c.embedding_text for c in chunks])
            await self.store.upsert_document(document, chunks, embeddings)
            report.documents_indexed += 1
            report.chunks_written += len(chunks)
            log.info("ingestion.document_indexed", doc_id=document.doc_id, chunks=len(chunks))

        stale = sorted(set(existing) - seen)
        if stale:
            await self.store.delete_documents(stale)
            report.documents_deleted = len(stale)
        return report
