"""Hybrid retriever: dense (embeddings) + lexical, fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import time

from backend.retrieval.embeddings import Embedder
from backend.retrieval.vector_store import VectorStore
from backend.schemas.domain import ChunkRecord, MetadataFilter, RetrievalResult, ScoredChunk


def reciprocal_rank_fusion(
    rankings: list[list[tuple[ChunkRecord, float]]], k: int = 60, weights: list[float] | None = None
) -> list[tuple[ChunkRecord, float]]:
    fused: dict[str, float] = {}
    chunks: dict[str, ChunkRecord] = {}
    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for rank, (chunk, _) in enumerate(ranking, start=1):
            fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0.0) + weight / (k + rank)
            chunks[chunk.chunk_id] = chunk
    ordered = sorted(fused.items(), key=lambda item: -item[1])
    return [(chunks[cid], score) for cid, score in ordered]


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        mode: str = "hybrid",
        candidate_k: int = 20,
        rrf_k: int = 60,
        lexical_weight: float = 1.0,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.mode = mode
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        self.lexical_weight = lexical_weight
        """Weight of the lexical ranking in the fusion (the dense ranking has weight 1)."""

    async def search(self, query: str, top_k: int, flt: MetadataFilter | None = None) -> RetrievalResult:
        started = time.perf_counter()
        depth = max(self.candidate_k, top_k)
        query_vector = await self.embedder.embed_query(query)
        dense = await self.store.vector_search(query_vector, depth, flt)
        dense_scores = {c.chunk_id: s for c, s in dense}

        if self.mode == "vector":
            chunks = [ScoredChunk(chunk=c, score=s, vector_score=s) for c, s in dense[:top_k]]
        else:
            lexical = await self.store.lexical_search(query, depth, flt)
            lexical_scores = {c.chunk_id: s for c, s in lexical}
            fused = reciprocal_rank_fusion([dense, lexical], k=self.rrf_k, weights=[1.0, self.lexical_weight])
            chunks = [
                ScoredChunk(
                    chunk=c,
                    score=s,
                    vector_score=dense_scores.get(c.chunk_id),
                    lexical_score=lexical_scores.get(c.chunk_id),
                )
                for c, s in fused[:top_k]
            ]
        return RetrievalResult(
            query=query,
            chunks=chunks,
            mode=self.mode,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
