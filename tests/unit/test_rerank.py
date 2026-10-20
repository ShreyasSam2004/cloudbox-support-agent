from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from backend.models.base import LLMRequest, LLMResponse, Usage
from backend.models.scripted import ScriptedProvider
from backend.retrieval.embeddings import HashingEmbedder
from backend.retrieval.evaluator import RetrievalEvaluator
from backend.retrieval.rerank import relabel, rerank
from backend.retrieval.retriever import Retriever
from backend.retrieval.vector_store import InMemoryVectorStore
from backend.security.auth import Principal
from backend.storage.sessions import Session
from backend.tools.base import ToolBudget, ToolContext
from backend.tools.evidence import EvidenceLedger
from backend.tools.knowledge_base import SearchKnowledgeBaseInput, SearchKnowledgeBaseTool
from tests.conftest import make_settings

LABELS = ["cand-1", "cand-2", "cand-3", "cand-4"]
QUERY = "refund after cancellation"


def test_rerank_orders_by_score_and_keeps_fused_order_for_ties() -> None:
    scores = {"cand-1": 1, "cand-2": 0, "cand-3": 3, "cand-4": 1}
    assert rerank(LABELS, scores, 3) == ["cand-3", "cand-1", "cand-4"]


def test_rerank_without_scores_is_fused_order() -> None:
    assert rerank(LABELS, {}, 2) == ["cand-1", "cand-2"]


def test_rerank_never_drops_passages_the_evaluator_skipped() -> None:
    assert rerank(LABELS, {"cand-2": 0, "cand-3": 2}, 4) == ["cand-3", "cand-1", "cand-4"]


def test_rerank_keeps_top_fused_results_when_nothing_is_relevant() -> None:
    assert rerank(LABELS, dict.fromkeys(LABELS, 0), 4) == ["cand-1", "cand-2"]


def test_relabel_maps_kept_candidates_to_evidence_ids() -> None:
    text = "cand-3 states the rule; Cand-7 is about invoices. P1 incidents are unrelated."
    assert relabel(text, {"cand-3": "K1"}) == (
        "K1 states the rule; a lower-ranked passage is about invoices. P1 incidents are unrelated."
    )


def _best_is_last(request: LLMRequest) -> LLMResponse:
    labels = re.findall(r'<passage id="([^"]+)"', request.messages[-1].text)
    payload = {
        "passage_scores": [{"id": label, "score": 1} for label in labels[:-1]]
        + [{"id": labels[-1].upper(), "score": 3}],
        "relevant": True,
        "confidence": 0.9,
        "coverage": "full",
        "missing_information": "",
        "reason": f"{labels[-1]} states the rule.",
    }
    return LLMResponse(
        text=json.dumps(payload), usage=Usage(input_tokens=1, output_tokens=1), model="m", provider="scripted"
    )


def _ctx() -> ToolContext:
    settings = make_settings()
    return ToolContext(
        execution_id=uuid.uuid4().hex,
        session=Session(session_id="s", owner="t"),
        principal=Principal(subject="t", customer_id=None, authenticated=False),
        user_message="Can I get a refund after cancelling?",
        ledger=EvidenceLedger(),
        settings=settings,
        now=datetime(2026, 10, 9, tzinfo=UTC),
        budget=ToolBudget(max_calls=5),
    )


async def test_search_tool_reranks_a_candidate_pool(kb_store: InMemoryVectorStore) -> None:
    retriever = Retriever(kb_store, HashingEmbedder(256))
    fused = await retriever.search(QUERY, top_k=8)
    evaluator_llm = ScriptedProvider(_best_is_last)
    tool = SearchKnowledgeBaseTool(
        retriever, RetrievalEvaluator(evaluator_llm), default_top_k=3, rerank_pool=8
    )
    ctx = _ctx()
    output = await tool.run(SearchKnowledgeBaseInput(query=QUERY), ctx)

    assert evaluator_llm.requests[0].messages[0].text.count("<passage ") == 8
    results = output.observation["results"]
    assert len(results) == 3 and len(ctx.ledger) == 3  # only returned passages become citable
    assert results[0]["section"] == fused.chunks[-1].chunk.section_path  # promoted from rank 8
    assert results[0]["evaluator_score"] == 3
    assert [r["section"] for r in results[1:]] == [c.chunk.section_path for c in fused.chunks[:2]]
    evaluation = output.observation["retrieval_evaluation"]
    assert evaluation["useful_evidence_ids"] == ["K1"]
    assert evaluation["reason"] == "K1 states the rule."
    assert output.observation["candidates_reranked"] == 8


async def test_search_tool_without_rerank_pool_keeps_fused_order(kb_store: InMemoryVectorStore) -> None:
    retriever = Retriever(kb_store, HashingEmbedder(256))
    fused = await retriever.search(QUERY, top_k=3)
    evaluator_llm = ScriptedProvider(_best_is_last)
    tool = SearchKnowledgeBaseTool(retriever, RetrievalEvaluator(evaluator_llm), default_top_k=3)
    output = await tool.run(SearchKnowledgeBaseInput(query=QUERY), _ctx())

    assert evaluator_llm.requests[0].messages[0].text.count("<passage ") == 3
    assert [r["section"] for r in output.observation["results"]] == [
        c.chunk.section_path for c in fused.chunks
    ]
    assert "candidates_reranked" not in output.observation
