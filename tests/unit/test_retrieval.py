"""Retrieval tests over the real corpus (hashing embeddings → these exercise the lexical half of hybrid)."""

from __future__ import annotations

import pytest

from backend.retrieval.bm25 import tokenize
from backend.retrieval.embeddings import HashingEmbedder
from backend.retrieval.ingestion import IngestionPipeline
from backend.retrieval.retriever import Retriever, reciprocal_rank_fusion
from backend.retrieval.vector_store import IndexMismatchError, InMemoryVectorStore
from backend.schemas.domain import ChunkRecord, MetadataFilter
from tests.conftest import DATA


def _chunk(cid: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=cid, doc_id="d", title="t", section_path="s", content="c", embedding_text="c", ordinal=0
    )


def test_tokenizer_keeps_compound_tokens_and_parts() -> None:
    tokens = tokenize("Error CBX-4292 quota_exceeded")
    assert {"cbx-4292", "cbx", "4292", "quota_exceeded", "quota", "exceeded"} <= set(tokens)


def test_rrf_rewards_agreement() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    fused = reciprocal_rank_fusion([[(a, 0.9), (b, 0.8)], [(b, 5.0), (c, 4.0)]])
    assert [chunk.chunk_id for chunk, _ in fused][0] == "b"


def test_rrf_weights_shift_ties_toward_the_heavier_ranking() -> None:
    a, c = _chunk("a"), _chunk("c")
    dense, lexical = [(a, 0.9)], [(c, 5.0)]
    assert reciprocal_rank_fusion([dense, lexical])[0][1] == reciprocal_rank_fusion([dense, lexical])[1][1]
    weighted = reciprocal_rank_fusion([dense, lexical], weights=[1.0, 0.5])
    assert [chunk.chunk_id for chunk, _ in weighted] == ["a", "c"]


@pytest.mark.parametrize(
    ("query", "expected_doc"),
    [
        ("quota_exceeded CBX-4292 monthly quota", "api-rate-limits"),
        ("rotate API key grace period 24 hours", "api-authentication"),
        ("account locked 3 times within 24 hours verification", "account-security"),
        ("SLA service credits claim within 30 days", "sla"),
        ("pending authorization hold released by bank", "billing-policy"),
    ],
)
async def test_hybrid_search_finds_expected_document(
    kb_store: InMemoryVectorStore, query: str, expected_doc: str
) -> None:
    retriever = Retriever(kb_store, HashingEmbedder(256))
    result = await retriever.search(query, top_k=5)
    assert expected_doc in [c.chunk.doc_id for c in result.chunks]


async def test_metadata_filter_restricts_documents(kb_store: InMemoryVectorStore) -> None:
    retriever = Retriever(kb_store, HashingEmbedder(256))
    result = await retriever.search("refund", top_k=5, flt=MetadataFilter(doc_ids=["enterprise-addendum"]))
    assert result.chunks
    assert {c.chunk.doc_id for c in result.chunks} == {"enterprise-addendum"}
    by_type = await retriever.search("refund", top_k=5, flt=MetadataFilter(doc_types=["faq"]))
    assert {c.chunk.metadata["doc_type"] for c in by_type.chunks} == {"faq"}


async def test_ingestion_is_idempotent_and_persists(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "index.json"
    store = InMemoryVectorStore(path)
    pipeline = IngestionPipeline(store, HashingEmbedder(64))
    first = await pipeline.ingest_directory(DATA / "knowledge_base")
    second = await pipeline.ingest_directory(DATA / "knowledge_base")
    assert first.documents_indexed == first.documents_seen > 0
    assert second.documents_indexed == 0 and second.documents_unchanged == first.documents_seen
    reloaded = InMemoryVectorStore(path)
    assert await reloaded.chunk_count() == first.chunks_written


async def test_stale_documents_are_deleted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "kb"
    source.mkdir()
    for name in ("faq.md", "sla.md"):
        (source / name).write_text(
            (DATA / "knowledge_base" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    store = InMemoryVectorStore(None)
    pipeline = IngestionPipeline(store, HashingEmbedder(64))
    await pipeline.ingest_directory(source)
    (source / "sla.md").unlink()
    report = await pipeline.ingest_directory(source)
    assert report.documents_deleted == 1
    assert [d.doc_id for d in await store.list_documents()] == ["faq"]


async def test_embedding_model_mismatch_is_refused() -> None:
    store = InMemoryVectorStore(None)
    await IngestionPipeline(store, HashingEmbedder(64)).ingest_directory(DATA / "knowledge_base")
    with pytest.raises(IndexMismatchError):
        await store.ensure_index("other-model", 64)
