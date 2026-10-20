"""Vector store interface and the in-process implementation.

``PgVectorStore`` (``pgvector_store.py``) is the production store. ``InMemoryVectorStore`` implements
the same contract with exact cosine search (NumPy) and BM25; it backs unit tests and lightweight local
runs, and can persist to a JSON file so ingestion and serving can be separate processes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import numpy as np

from backend.retrieval.bm25 import BM25Index
from backend.schemas.domain import ChunkRecord, DocumentRecord, MetadataFilter


class IndexMismatchError(RuntimeError):
    """The index was built with a different embedding model/dimension than the one configured."""


class VectorStore(Protocol):
    async def ensure_index(self, embedding_model: str, dim: int) -> None: ...

    async def document_hashes(self) -> dict[str, str]: ...

    async def upsert_document(
        self, doc: DocumentRecord, chunks: list[ChunkRecord], embeddings: list[list[float]]
    ) -> None: ...

    async def delete_documents(self, doc_ids: list[str]) -> None: ...

    async def list_documents(self) -> list[DocumentRecord]: ...

    async def vector_search(
        self, embedding: list[float], k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]: ...

    async def lexical_search(
        self, query: str, k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]: ...

    async def chunk_count(self) -> int: ...


def _matches(chunk: ChunkRecord, flt: MetadataFilter | None) -> bool:
    if flt is None or flt.is_empty():
        return True
    if flt.doc_ids and chunk.doc_id not in flt.doc_ids:
        return False
    return not (flt.doc_types and chunk.metadata.get("doc_type") not in flt.doc_types)


class InMemoryVectorStore:
    def __init__(self, persist_path: Path | None = None) -> None:
        self._persist_path = persist_path
        self._docs: dict[str, DocumentRecord] = {}
        self._chunks: dict[str, list[ChunkRecord]] = {}
        self._vectors: dict[str, list[list[float]]] = {}
        self._meta: tuple[str, int] | None = None
        self._flat: list[ChunkRecord] = []
        self._matrix: np.ndarray | None = None
        self._bm25: BM25Index | None = None
        if persist_path is not None and persist_path.exists():
            self._load(persist_path)

    # ------------------------------------------------------------------ persistence

    def _load(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._meta = (data["embedding_model"], int(data["dim"]))
        for item in data["documents"]:
            doc = DocumentRecord.model_validate(item["document"])
            self._docs[doc.doc_id] = doc
            self._chunks[doc.doc_id] = [ChunkRecord.model_validate(c) for c in item["chunks"]]
            self._vectors[doc.doc_id] = item["vectors"]
        self._rebuild()

    def save(self) -> None:
        if self._persist_path is None or self._meta is None:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_model": self._meta[0],
            "dim": self._meta[1],
            "documents": [
                {
                    "document": self._docs[doc_id].model_dump(mode="json"),
                    "chunks": [c.model_dump(mode="json") for c in self._chunks[doc_id]],
                    "vectors": [[round(x, 6) for x in v] for v in self._vectors[doc_id]],
                }
                for doc_id in sorted(self._docs)
            ],
        }
        self._persist_path.write_text(json.dumps(payload), encoding="utf-8")

    def _rebuild(self) -> None:
        self._flat = [c for doc_id in sorted(self._chunks) for c in self._chunks[doc_id]]
        vectors = [v for doc_id in sorted(self._vectors) for v in self._vectors[doc_id]]
        self._matrix = np.asarray(vectors, dtype=np.float32) if vectors else None
        self._bm25 = BM25Index([c.embedding_text for c in self._flat]) if self._flat else None

    # ------------------------------------------------------------------ contract

    async def ensure_index(self, embedding_model: str, dim: int) -> None:
        if self._meta is not None and self._meta != (embedding_model, dim) and self._docs:
            raise IndexMismatchError(
                f"index built with {self._meta[0]} (dim {self._meta[1]}), configured {embedding_model} "
                f"(dim {dim}); re-ingest with --force"
            )
        self._meta = (embedding_model, dim)

    async def document_hashes(self) -> dict[str, str]:
        return {doc_id: doc.content_hash for doc_id, doc in self._docs.items()}

    async def upsert_document(
        self, doc: DocumentRecord, chunks: list[ChunkRecord], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        self._docs[doc.doc_id] = doc
        self._chunks[doc.doc_id] = chunks
        self._vectors[doc.doc_id] = embeddings
        self._rebuild()
        self.save()

    async def delete_documents(self, doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            self._docs.pop(doc_id, None)
            self._chunks.pop(doc_id, None)
            self._vectors.pop(doc_id, None)
        self._rebuild()
        self.save()

    async def list_documents(self) -> list[DocumentRecord]:
        return [self._docs[d] for d in sorted(self._docs)]

    async def vector_search(
        self, embedding: list[float], k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]:
        if self._matrix is None:
            return []
        scores = self._matrix @ np.asarray(embedding, dtype=np.float32)
        order = np.argsort(-scores)
        out: list[tuple[ChunkRecord, float]] = []
        for idx in order:
            chunk = self._flat[int(idx)]
            if _matches(chunk, flt):
                out.append((chunk, float(scores[idx])))
                if len(out) >= k:
                    break
        return out

    async def lexical_search(
        self, query: str, k: int, flt: MetadataFilter | None = None
    ) -> list[tuple[ChunkRecord, float]]:
        if self._bm25 is None:
            return []
        scores = self._bm25.scores(query)
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
        out: list[tuple[ChunkRecord, float]] = []
        for idx in ranked:
            if scores[idx] <= 0:
                break
            chunk = self._flat[idx]
            if _matches(chunk, flt):
                out.append((chunk, scores[idx]))
                if len(out) >= k:
                    break
        return out

    async def chunk_count(self) -> int:
        return len(self._flat)
