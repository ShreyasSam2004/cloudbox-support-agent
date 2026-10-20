"""Retrieval benchmark: label integrity and the scoring helpers (no network)."""

from __future__ import annotations

from backend.evaluation.dataset import EvalCase, load_dataset
from backend.evaluation.retrieval_bench import (
    STRATEGIES,
    _windows,
    aggregate,
    chunk_corpus,
    found_phrases,
    normalize,
    score_ranking,
)
from backend.schemas.domain import ChunkRecord
from tests.conftest import DATA

DATASET = DATA / "eval" / "cloudbox_support_v1.jsonl"


def _sources() -> list[tuple[str, str]]:
    return [(p.as_posix(), p.read_text("utf-8")) for p in sorted((DATA / "knowledge_base").glob("*.md"))]


def test_every_evidence_phrase_exists_verbatim_in_the_knowledge_base() -> None:
    """Editing a document must not silently invalidate the retrieval labels."""
    corpus = [normalize(raw) for _, raw in _sources()]
    cases = [c for c in load_dataset(DATASET) if c.evidence]
    assert len(cases) >= 30
    for case in cases:
        assert case.expected_behavior != "refuse", case.id
        for phrase in case.evidence:
            assert any(normalize(phrase) in doc for doc in corpus), (case.id, phrase)


def test_structured_chunks_keep_every_evidence_phrase_intact() -> None:
    chunks = [c.content for _, records in chunk_corpus(STRATEGIES[0], _sources()) for c in records]
    for case in load_dataset(DATASET):
        assert len(found_phrases(case.evidence, chunks)) == len(case.evidence), case.id


def test_normalize_ignores_markdown_emphasis_tables_and_dashes() -> None:
    assert normalize("Fees are **non-refundable**, incl. | `Pro` | 5–10 days") == (
        "fees are non-refundable, incl. pro 5-10 days"
    )


def test_fixed_windows_cover_the_text_with_overlap() -> None:
    body = " ".join(f"w{i}" for i in range(400))
    windows = _windows(body, 200, 40)
    assert windows[0].startswith("w0") and windows[-1].endswith("w399")
    assert all(len(w) <= 200 for w in windows)
    assert windows[0].split()[-1] in windows[1]  # consecutive windows overlap


def _chunk(text: str, i: int) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"d::{i}",
        doc_id="d",
        title="D",
        section_path="D",
        content=text,
        embedding_text=text,
        ordinal=i,
    )


def test_score_ranking_recall_complete_mrr_and_budget() -> None:
    case = EvalCase(
        id="x", category="c", question="q", expected_behavior="answer", evidence=["alpha rule", "beta rule"]
    )
    ranking = [_chunk("noise " * 50, 0), _chunk("the ALPHA rule", 1), _chunk("**beta** rule", 2)]
    row = score_ranking(case, ranking, view_chars=2000)
    assert row["first_hit"] == 2
    assert row["per_k"][1]["found"] == 0 and row["per_k"][2]["found"] == 1
    assert row["per_k"][3]["complete"] is True
    assert row["per_budget"][1500] == 2  # 300 + 14 + 12 chars fit
    summary = aggregate([row])
    assert summary["recall@2"] == 0.5 and summary["complete@3"] == 1.0 and summary["mrr"] == 0.5
